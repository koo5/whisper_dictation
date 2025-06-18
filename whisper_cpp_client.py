#!/usr/bin/python
# -*- coding: utf-8 -*-
##
## Copyright 2023-2025 Henry Kroll <nospam@thenerdshow.com>
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
## MA 02110-1301, USA.
##
import pyautogui
import os, sys
import time
import queue
import re
from openai import OpenAI, NotGiven

import webbrowser
import tempfile
import threading
import requests
import logging
import tracer
from mimic3_client import say, shutup
from on_screen import camera, show_pictures
from record import delayRecord
audio_queue = queue.Queue()
listening = True
chatting = False
record_process = None
running = True
cam = None

# Define debug mode early
debug = os.getenv("DEBUG_WHISPER", "false").lower() in ["true", "1", "yes", "y"]

# Check if quiet mode is enabled
quiet_mode = os.getenv("QUIET", "false").lower() in ["true", "1", "yes", "y"]

# Check if newline mode is enabled
newline_mode = os.getenv("NEWLINE", "false").lower() in ["true", "1", "yes", "y"]

# Check if key sending is disabled
no_keys = os.getenv("NO_KEYS", "false").lower() in ["true", "1", "yes", "y"]

# Status indicator settings
show_status = os.getenv("SHOW_PROCESSING_STATUS", "false").lower() in ["true", "1", "yes", "y"]
processing_color = os.getenv("PROCESSING_COLOR", "\033[1;33m")  # Default: Yellow
idle_color = os.getenv("IDLE_COLOR", "\033[1;32m")              # Default: Green

# Language setting
whisper_language =  os.getenv("WHISPER_LANGUAGE", NotGiven())
# Model setting for OpenAI Whisper API
whisper_model = os.getenv("WHISPER_MODEL", "whisper-1")  # Default: whisper-1

# Ignore patterns for transcriptions
ignore_patterns = os.getenv("IGNORE_PATTERNS", "")
if not ignore_patterns and whisper_language:
    # Only apply default patterns if language is explicitly set
    lang = str(whisper_language).lower()
    if lang == "cs":
        # Regex pattern for Czech - some are substring matches, some are exact
        ignore_patterns = (
            # Substring matches (anywhere in text)
            r"http://johnyxcz\.blogspot\.com|" +
            r"http://johnyxcz\.com|" +
            r"Titulky vytvořil JohnyX|" +
            r"www\.hradeckesluzby\.cz|" +
            r"www\.arkance-systems\.cz|" +
            r"děkujeme za pozornost"
        )
    elif lang == "en":
        # Regex pattern for English - exact matches for common whisper artifacts
        ignore_patterns = r"^Thanks for watching!?\s*$|^you\s*$"

reset_color = os.getenv("RESET_COLOR", "\033[0m")               # Default: Reset

def show_processing_status():
    """Display processing status indicator"""
    if show_status:
        output = f"{bs}{processing_color}[PROCESSING]{reset_color} Analyzing speech..."
        if quiet_mode:
            print(output, end="", flush=True, file=sys.stderr)
        else:
            print(output, end="", flush=True)

def show_idle_status():
    """Display idle status indicator"""
    if show_status:
        output = f"{bs}{idle_color}[IDLE]{reset_color} Waiting for speech input..."
        if quiet_mode:
            print(output, end="", flush=True, file=sys.stderr)
        else:
            print(output, end="", flush=True)

# Enable debug logging if DEBUG_WHISPER env var is set
log_level = logging.DEBUG if debug else logging.INFO

# In quiet mode, send logs to stderr
if quiet_mode:
    logging.basicConfig(
        level=log_level,
        format="[%(levelname)s] %(funcName)s:%(lineno)d %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr)
        ]
    )
else:
    logging.basicConfig(
        level=log_level,
        format="[%(levelname)s] %(funcName)s:%(lineno)d %(message)s",
        handlers=[
#            logging.FileHandler('/tmp/whisper_cpp_client.log'),
            logging.StreamHandler()
        ]
    )

# bs = "\b" * 99 # if your terminal does not support ANSI
bs = "\033[1K\r"

if debug:
    logging.debug(f"Debug mode enabled")
    logging.debug(f"OpenAI Whisper enabled: {os.getenv('USE_OPENAI_WHISPER', 'false')}")
    logging.debug(f"Show processing status: {show_status}")

# address of whisper.cpp server
cpp_url = "http://127.0.0.1:7777/inference"
# address of Fallback Chat Server.
fallback_chat_url = "http://localhost:8888/v1"

# OpenAI API configuration
gpt_key = os.getenv("OPENAI_API_KEY")
client = None
openai_whisper = False  # Flag to use OpenAI's Whisper API instead of local server

if gpt_key:
    from openai import OpenAI
    client = OpenAI(api_key=gpt_key)
    # Check if user wants to use OpenAI for transcription
    openai_whisper = os.getenv("USE_OPENAI_WHISPER", "false").lower() in ["true", "1", "yes", "y"]
    if openai_whisper:
        msg = "Using OpenAI's Whisper API for speech recognition"
    else:
        msg = "Using local whisper.cpp server for speech recognition"
        
    if quiet_mode:
        print(msg, file=sys.stderr)
        if not openai_whisper:
            print("Set USE_OPENAI_WHISPER=true to use OpenAI's Whisper API instead", file=sys.stderr)
    else:
        print(msg)
        if not openai_whisper:
            print("Set USE_OPENAI_WHISPER=true to use OpenAI's Whisper API instead")
    
    logging.debug("OpenAI API key found. ChatGPT responses available.\n")
else:
    logging.debug("Export OPENAI_API_KEY if you want answers from ChatGPT or use Whisper API.\n")

# Log audio device info if in debug mode
if debug:
    try:
        import subprocess
        # Try to get audio device info
        result = subprocess.run(['pactl', 'list', 'short', 'sources'], 
                              capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            logging.debug("Audio input devices:")
            for line in result.stdout.strip().split('\n'):
                if line:
                    logging.debug(f"  {line}")
    except Exception as e:
        logging.debug(f"Could not list audio devices: {e}")

gem_key = os.getenv("GENAI_TOKEN")
if (gem_key):
    import google.generativeai as genai
    genai.configure(api_key=gem_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    logging.debug("Gemini API key found. Gemini responses available.\n")
else:
    logging.debug("Export GENAI_TOKEN if you want answers from Gemini.\n")

# commands and hotkeys for various platforms
commands = {
"windows": {
    "file manager":  "start explorer",
    "terminal":     "start cmd",
    "browser":      "start iexplore",
    "web browser":  "start iexplore",
    "webcam":       "on_screen.py",
    },

"linux": {
    "file manager":  "nemo --no-desktop&",
    "terminal":     "xterm -bg gray20 -fg gray80 -fa 'Liberation Sans Mono' -fs 12 -rightbar&",
    "browser":      "htmlview&",
    "web browser":   "htmlview&",
    "webcam":       "./on_screen.py",
    },
}
hotkeys = {
    r"^new paragraph.?$": [['backspace'], ['enter'],['enter']],
    r"^(new li[nm]e|press enter|submit).?$": [['backspace'],['enter']],
    r"^back ?space.?$":   [['backspace']],
    r"^space.?$":         [['space']],
    r"^go up.?$":         [['up']],
    r"^go down.?$":       [['down']],
    r"^go right.?$":      [['right']],
    r"^go left.?$":       [['left']],
    r"^go home.?$":       [['home']],
    r"^go (to the )?end.?$": [['end']],
    r"^page up.?$":    	  [['pageup']],
    r"^page down.?$":     [['pagedown']],
    r"^select all.?$":    [['ctrl', 'a']],
    r"^undo that.?$":     [['ctrl', 'z']],
    r"^cut line.?$":      [['ctrl', 'l']],
    r"^copy that.?$":     [['ctrl', 'c']],
    r"^paste it.?$":      [['ctrl', 'v']],
    }
actions = {
    r"^left click.?$": "pyautogui.click()",
    r"^(click)( the)?( mouse).?": "pyautogui.click()",
    r"^middle click.?$": "pyautogui.middleClick()",
    r"^right click.?$": "pyautogui.rightClick()",
    r"^directory listing.?$": "pyautogui.write('ls\n')",
    r"^(peter|samantha|computer).?,? (run|open|start|launch)(up)?( a| the)? ": "os.system(commands[sys.platform][q])",
    r"^(peter|samantha|computer).?,? closed? window": "pyautogui.hotkey('alt', 'F4')",
    r"^(peter|samantha|computer).?,? search( the)?( you| web| google| bing| online)?(.com)? for ": 
       "webbrowser.open('https://you.com/search?q=' + re.sub(' ','%20',q))",
    r"^(peter|samantha|computer).?,? (send|compose|write)( an| a) email to ": "os.popen('xdg-open \"mailto://' + q.replace(' at ', '@') + '\"')",
    r"^(peter|samantha|computer).?,? (i need )?(let's )?(see |have |show )?(us |me )?(an? )?(image|picture|draw|create|imagine|paint)(ing| of)? ": "os.popen(f'./sdapi.py \"{q}\"')",
    r"^(peter|samantha|computer)?.?,? ?(resume|zoom|continue|start|type|thank|got|whoa|that's) (typing|d.ctation|this|you|there|enough|it)" : "resume_dictation()",
    r"^(peter|samantha|computer)?.?,? ?(record)( a| an| my)?( audio| sound| voice| file| clip)+" : "record_mp3()",
    r"^(peter|samantha|computer)?.?,? ?(on|show|start|open) (the )?(webcam|camera|screen)" : "on_screen()",
    r"^(peter|samantha|computer)?.?,? ?(off|stop|close) (the )?(webcam|camera|screen)" : "off_screen()",
    r"^(peter|samantha|computer)?.?,? ?(take|snap) (a|the|another) (photo|picture)" : "take_picture()",
    r"^(peter|samantha|computer)?.?,? ?(show|view) (the )?(photo|photos|pictures)( album| collection)?" : "show_pictures()",
    r"^(peter|samantha|computer).?,? ": "generate_text(q)"
    }

def process_actions(tl:str) -> bool:
    global chatting
    global listening
    for input, action in actions.items():
        # look for action in list
        if s:=re.search(input, tl):
            # Skip pyautogui actions if NO_KEYS is set
            if no_keys and "pyautogui" in action:
                continue
            q = tl[s.end():] # get q for action
            if not quiet_mode:
                say("okay")
            eval(action)
            if debug:
                if quiet_mode:
                    print(q, file=sys.stderr)
                else:
                    print(q)
            return True # success
    if chatting:
        generate_text(tl); return True
    return False # no action

def on_screen():
    global cam
    if not cam: cam = camera()
    cam.pipeline.set_state(cam.on)
    return cam

def take_picture():
    global cam
    on = cam
    cam = on_screen()
    time.sleep(0.5)
    cam.take_picture()
    if not on: # don't leave camera on, unless already on
        time.sleep(1.0)
        off_screen()

def off_screen():
    global cam
    if cam: cam = cam.stop_camera()

# search text for hotkeys
def process_hotkeys(txt: str) -> bool:
    if no_keys:
        return False  # Don't process hotkeys if key sending is disabled
    for key,val in hotkeys.items():
        # if hotkey command
        if re.search(key, txt):
            # unpack list of key combos such as ctrl-v
            for x in val:
                # press each key combo in turn
                # The * unpacks x to separate args
                pyautogui.hotkey(*x)
            return True
    return False

def gettext(f:str) -> str:
    """
    Convert audio file to text using either local whisper.cpp server or OpenAI's Whisper API
    """
    result = ['']
    if not f or not os.path.isfile(f):
        logging.debug(f"gettext: Invalid file: {f}")
        return ""
    
    file_size = os.path.getsize(f)
    logging.debug(f"gettext: Processing audio file: {f} (size: {file_size} bytes)")
    
    # Show processing status
    show_processing_status()
        
    # If OpenAI's Whisper API is enabled and API key is available
    if openai_whisper and client:
        try:
            with open(f, "rb") as audio_file:
                logging.debug("Sending audio to OpenAI Whisper API...")
                start_time = time.time()
                
                # Add timeout for API call
                api_timeout = float(os.getenv("OPENAI_API_TIMEOUT", "30"))  # Default 30 seconds
                
                try:
                    logging.info(f"Transcribing audio file '{f}' using OpenAI Whisper API with timeout {api_timeout} seconds")
                    transcription = client.audio.transcriptions.create(
                        model=whisper_model,
                        file=audio_file,
                        language=whisper_language,
                        temperature=0.0,
                        response_format="text",
                        timeout=api_timeout
                    )
                except Exception as api_error:
                    if "timeout" in str(api_error).lower():
                        logging.error(f"OpenAI API timeout after {api_timeout} seconds")
                    raise api_error
                    
                elapsed = time.time() - start_time
                logging.debug(f"OpenAI API response received in {elapsed:.2f} seconds")
                logging.debug(f"Transcription text: '{transcription}'")
                # Show idle status after processing
                show_idle_status()
                # OpenAI API returns text directly
                return transcription
                
        except Exception as e:
            logging.error(f"{bs}OpenAI API Error: {e}")
            logging.info("Falling back to local server...")
            # Fall back to local server if OpenAI API fails
    
    # Use local whisper.cpp server
    try:
        logging.debug("Sending audio to local whisper.cpp server...")
        files = {'file': (f, open(f, 'rb'))}
        # Enhanced parameters for better recognition
        data = {
            'temperature': '0.0',      # Lower temperature for more deterministic output
            'response_format': 'json', 
            'word_timestamps': 'true', # Get word-level timestamps
            'language': whisper_language,  # Use configured language
            'beam_size': '5',          # Increase beam size for better accuracy
        }

        response = requests.post(cpp_url, files=files, data=data)
        response.raise_for_status()  # Check for errors

        # Parse the JSON response
        result = [response.json()]
        
        # Show idle status after processing
        show_idle_status()
        return result[0]['text']

    except requests.exceptions.RequestException as e:
        logging.error(f"{bs}Local Server Error: {e}")
        # Show idle status even after error
        show_idle_status()
        return ""
    
    # Show idle status if we somehow reached here
    show_idle_status()
    return ""

# Print startup messages
if quiet_mode:
    print("Tab over to another window and start speaking.", file=sys.stderr)
    print("Text should appear in the window you are working in.", file=sys.stderr)
    print("Say \"Stop listening.\" or press CTRL-C to stop.", file=sys.stderr)
    if debug:
        print("\n[DEBUG MODE ACTIVE - Detailed logs will be shown]", file=sys.stderr)
        print(f"Recording timeout: {os.getenv('RECORDING_TIMEOUT', '10')} seconds", file=sys.stderr)
        print(f"OpenAI API timeout: {os.getenv('OPENAI_API_TIMEOUT', '30')} seconds\n", file=sys.stderr)
else:
    print("Tab over to another window and start speaking.")
    print("Text should appear in the window you are working in.")
    print("Say \"Stop listening.\" or press CTRL-C to stop.")
    if debug:
        print("\n[DEBUG MODE ACTIVE - Detailed logs will be shown]")
        print(f"Recording timeout: {os.getenv('RECORDING_TIMEOUT', '10')} seconds")
        print(f"OpenAI API timeout: {os.getenv('OPENAI_API_TIMEOUT', '30')} seconds\n")
    say("All systems ready.")

# Show initial idle status indicator
show_idle_status()

if debug:
    logging.debug("System initialized, starting main loops...")

messages = [{ "role": "system", "content": "In this conversation between `user:` and `assistant:`, play the role of assistant. Reply as a helpful assistant." },]

def generate_text(prompt: str):
    conversation_length = 9 # try increasing if AI model has a large ctx window
    global chatting, messages, gpt_key, gem_key
    messages.append({"role": "user", "content": prompt})
    completion = ""
    
    # Show processing status for AI generation
    if show_status:
        output = f"{bs}{processing_color}[PROCESSING]{reset_color} Generating AI response..."
        if quiet_mode:
            print(output, end="", flush=True, file=sys.stderr)
        else:
            print(output, end="", flush=True)
    
    # Try chatGPT
    if gpt_key and client:
        logging.debug(f"{bs}Asking ChatGPT")
        try:
            completion = client.chat.completions.create(model="gpt-3.5-turbo",
            messages=messages)
            completion = completion.choices[0].message.content
        except Exception as e:
                logging.debug("ChatGPT had a problem. Here's the error message.")
                logging.debug(e)

    # Fallback to Google Gemini
    elif gem_key and not completion:
        logging.debug("Asking Gemini")
        chat = model.start_chat(
            history=[
            {"role": "user" if x["role"] == "user" else "model",
                "parts": x["content"]}for x in messages]
        )
        response = chat.send_message(prompt)
        completion = response.text

    # Fallback to localhost
    if not completion:
        logging.debug(f"Querying {fallback_chat_url}")
        # ref. llama.cpp/examples/server/README.md
        try:
            import openai
            client = openai.OpenAI(
            base_url=fallback_chat_url,
            api_key = "sk-no-key-required")
            completion = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages
            )
            completion = completion.choices[0].message.content
        except Exception as e:
            logging.debug(f"Error: {e}")
            completion = "I'm sorry, I can't assist with that right now."

    # Show idle status after processing
    show_idle_status()

    if completion:
        if quiet_mode:
            print(f"{bs}{completion}", file=sys.stderr)
        else:
            print(f"{bs}{completion}")
        # handle queries for more information
        if "more information?" in completion or \
            "It sounds like" in completion or \
            "It seems like" in completion or \
            "you tell me" in completion or \
            "Could you please" in completion or \
            "a large language model" in completion or \
            completion == "< nooutput >":
            if not quiet_mode:
                say("Sorry, I didn't catch that. Can you give me more information, please?")
            chatting = False # allow dictation into the prompt box
            response = pyautogui.prompt("More information, please.",
            "Please clarify.", prompt)
            # on user cancel, stop AI chat & resume dictation
            if not response: return None
            # otherwise, process the new query
            chatting = True
            return generate_text(response)
        if not no_keys:
            pyautogui.write(completion)
        if not quiet_mode:
            say(completion)
        chatting = True
        # add to conversation
        messages.append({"role": "assistant", "content": completion})
        if len(messages) > conversation_length:
            messages.remove(messages[1])
            messages.remove(messages[1])

def resume_dictation():
    global chatting, listening
    chatting = False
    listening = True

def transcribe():
    global listening
    iteration_count = 0
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    while True:
        try:
            iteration_count += 1
            if debug:
                logging.debug(f"Transcribe loop iteration {iteration_count}, queue size: {audio_queue.qsize()}")
            
            # Get audio from queue with timeout to prevent hanging
            try:
                f = audio_queue.get(timeout=5.0)  # 5 second timeout
            except queue.Empty:
                if debug and iteration_count % 12 == 0:  # Log every minute
                    logging.debug("No audio in queue, continuing...")
                continue
                
            if f:
                logging.debug(f"Got audio file from queue: {f}")
                txt = gettext(f)
                # delete temporary audio file
                try: 
                    #os.remove(f)
                    logging.debug(f"Deleted temp file: {f}")
                except Exception as e: 
                    logging.debug(f"Failed to delete temp file {f}: {e}")
                if not txt: 
                    logging.debug("No text returned from gettext, continuing...")
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        logging.error(f"Too many consecutive empty transcriptions ({consecutive_errors})")
                        logging.error("This might indicate audio device issues")
                        time.sleep(2)
                        consecutive_errors = 0
                    continue
                else:
                    consecutive_errors = 0  # Reset on successful transcription
                # filter space at beginning of lines
                txt = re.sub(r"(^|\n)\s", r"\1", txt)
                # print messages [BLANK_AUDIO], (swoosh), *barking*
                if re.search(r"[\(\[\*]", txt):
                    if quiet_mode:
                        print(bs + txt.strip(), file=sys.stderr)
                    else:
                        print(bs + txt.strip())
                    # filter it out
                    txt = re.sub(r'[\*\[\(][^\]\)]*[\]\)\*]*\s*$', '', txt)
                if txt == " ":
                    continue # ignoring empty
                
                # Check against ignore patterns
                if ignore_patterns and re.search(ignore_patterns, txt, re.IGNORECASE):
                    logging.debug(f"Ignoring transcription matching pattern: '{txt.strip()}'")
                    continue
                # get lower-case spoken command string
                lower_case = txt.lower().strip()
                if not lower_case: continue
                shutup() # stop bot from talking
                if match := re.search(r"[^\w\s]$", lower_case):
                    lower_case = lower_case[:match.start()] # remove punctuation
                # strip txt unless we specifically say "new paragraph"
                txt = txt.strip(' \n') + ' '
                if quiet_mode:
                    # In quiet mode, debug info goes to stderr
                    print(bs + txt, file=sys.stderr)
                else:
                    print(bs + txt) # print the text

                # see list of actions and hotkeys at top of file :)
                # Go to Website.
                if s:=re.search(r"^(peter|computer).? (go|open|browse|visit|navigate)( up| to| the| website)* [a-zA-Z0-9-]{1,63}(\.[a-zA-Z0-9-]{1,63})+$", lower_case):
                    q = lower_case[s.end():] # get q for command
                    webbrowser.open('https://' + q.strip())
                    continue
                # Stop dictation.
                elif re.search(r"^stop.? (d.ctation|listening).?$", lower_case):
                    if not quiet_mode:
                        say("Shutting down.")
                    break
                elif re.search(r"^paused? (d.ctation|positi.?i?cation).?$", lower_case):
                    listening = False
                    if not quiet_mode:
                        say("okay")
                elif process_actions(lower_case): continue
                if not listening: continue
                elif process_hotkeys(lower_case): continue
                elif len(txt) > 1:
                    logging.debug(f"Writing text to active window: '{txt}' (length: {len(txt)})")
                    try:
                        if not no_keys:
                            pyautogui.write(txt)
                        if quiet_mode:
                            # In quiet mode, print ONLY the transcribed text to stdout
                            output_text = txt.strip()
                            if newline_mode:
                                print(output_text)
                            else:
                                print(output_text, end='', flush=True)
                        logging.debug("Text written successfully")
                    except Exception as e:
                        logging.error(f"Failed to write text: {e}")
            # continue looping every 1/5 second
            else: 
                if debug and iteration_count % 50 == 0:  # Log every 10 seconds
                    logging.debug(f"Waiting for audio, iteration {iteration_count}")
                time.sleep(0.2)
        except KeyboardInterrupt:
            if not quiet_mode:
                say("Goodbye.")
            break
        except Exception as e:
            logging.error(f"Error in transcribe loop: {e}")
            consecutive_errors += 1
            if consecutive_errors >= max_consecutive_errors:
                logging.error("Too many errors in transcribe loop, pausing...")
                time.sleep(5)
                consecutive_errors = 0

def record_mp3():
    global listening
    listening = False
    if not quiet_mode:
        say("Recording audio clip...")
    time.sleep(1)
    rec = delayRecord("audio.mp3")
    rec.start()
    if not quiet_mode:
        say(f"Recording saved to {rec.file_name}")
    time.sleep(1)
    listening = True

def record_to_queue():
    global record_process
    global running
    recording_count = 0
    consecutive_errors = 0
    max_consecutive_errors = 5
    recording_timeout = float(os.getenv("RECORDING_TIMEOUT", "10"))  # Default 10 seconds
    
    while running:
        recording_count += 1
        temp_file = tempfile.mktemp()+ '.wav'
        logging.debug(f"Temporary file for recording #{recording_count}: {temp_file}")
        
        try:
            logging.debug(f"Starting recording #{recording_count} to file: {temp_file}")
            start_time = time.time()
            
            record_process = delayRecord(temp_file)
            record_process.stop_after = float(os.environ.get("STOP_AFTER", "2"))
            
            # Start recording in a separate thread to enable timeout
            recording_thread = threading.Thread(target=record_process.start)
            recording_thread.daemon = True
            recording_thread.start()
            
            # Wait for recording with timeout
            recording_thread.join(timeout=recording_timeout)
            
            if recording_thread.is_alive():
                logging.error(f"Recording #{recording_count} timed out after {recording_timeout} seconds")
                # Try to stop the recording
                if record_process:
                    try:
                        record_process.stop_recording()
                    except:
                        pass
                consecutive_errors += 1
                continue
            
            elapsed = time.time() - start_time
            logging.debug(f"Recording #{recording_count} completed in {elapsed:.2f} seconds")
            
            # Check if file was created and has content
            if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
                audio_queue.put(record_process.file_name)
                consecutive_errors = 0  # Reset error counter on success
            else:
                logging.error(f"Recording #{recording_count} produced empty or no file")
                consecutive_errors += 1
                
        except Exception as e:
            logging.error(f"Error during recording #{recording_count}: {e}")
            consecutive_errors += 1
            
        # If too many consecutive errors, pause and retry
        if consecutive_errors >= max_consecutive_errors:
            logging.error(f"Too many recording errors ({consecutive_errors}), pausing for 5 seconds...")
            logging.error("This might be due to audio device issues (e.g., Bluetooth disconnection)")
            time.sleep(5)
            consecutive_errors = 0
            
        if debug and recording_count % 10 == 0:
            logging.debug(f"Completed {recording_count} recordings so far")

def discard_input():
    if quiet_mode:
        print("\nShutdown complete. Press ENTER to return to terminal.", file=sys.stderr)
    else:
        print("\nShutdown complete. Press ENTER to return to terminal.")
    # discard input
    # in case dodo head dictated into the same terminal
    while input():
        time.sleep(0.1)

def quit():
    logging.debug("\nStopping...")
    global running
    global listening
    listening = False
    running = False
    if record_process:
        record_process.stop_recording()
    record_thread.join()
    # clean up
    try:
        while f := audio_queue.get_nowait():
            logging.debug(f"{bs}Removing temporary file: {f}")
            if f[:5] == "/tmp/": # safety check
                os.remove(f)
    except Exception: pass
    logging.debug("\nFreeing system resources.\n")
#    os.system("systemctl --user stop whisper")
    discard_input()
    if not quiet_mode:
        shutup()

if __name__ == '__main__':
    if debug:
        logging.debug("Starting whisper_cpp_client in debug mode")
        logging.debug(f"Audio queue initialized: {audio_queue}")
    record_thread = threading.Thread(target=record_to_queue)
#    os.system("systemctl --user start whisper")
    record_thread.start()
    if debug:
        logging.debug("Recording thread started")
    transcribe()
    quit()
