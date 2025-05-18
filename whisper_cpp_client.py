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
from openai import OpenAI

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

# Status indicator settings
show_status = os.getenv("SHOW_PROCESSING_STATUS", "false").lower() in ["true", "1", "yes", "y"]
processing_color = os.getenv("PROCESSING_COLOR", "\033[1;33m")  # Default: Yellow
idle_color = os.getenv("IDLE_COLOR", "\033[1;32m")              # Default: Green
reset_color = os.getenv("RESET_COLOR", "\033[0m")               # Default: Reset

def show_processing_status():
    """Display processing status indicator"""
    if show_status:
        print(f"{bs}{processing_color}[PROCESSING]{reset_color} Analyzing speech...", end="", flush=True)

def show_idle_status():
    """Display idle status indicator"""
    if show_status:
        print(f"{bs}{idle_color}[IDLE]{reset_color} Waiting for speech input...", end="", flush=True)

logging.basicConfig(
	level=logging.INFO,
	format="[%(levelname)s] %(lineno)d %(message)s",
	handlers=[
#		logging.FileHandler('/tmp/whisper_cpp_client.log'),
		logging.StreamHandler()
	]
)

# bs = "\b" * 99 # if your terminal does not support ANSI
bs = "\033[1K\r"

# address of whisper.cpp server
cpp_url = "http://127.0.0.1:7777/inference"
# address of Fallback Chat Server.
fallback_chat_url = "http://localhost:8888/v1"
debug = False

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
        print("Using OpenAI's Whisper API for speech recognition")
    else:
        print("Using local whisper.cpp server for speech recognition")
        print("Set USE_OPENAI_WHISPER=true to use OpenAI's Whisper API instead")
    logging.debug("OpenAI API key found. ChatGPT responses available.\n")
else:
    logging.debug("Export OPENAI_API_KEY if you want answers from ChatGPT or use Whisper API.\n")

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
            q = tl[s.end():] # get q for action
            say("okay")
            eval(action)
            if debug:
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
        return ""
    
    # Show processing status
    show_processing_status()
        
    # If OpenAI's Whisper API is enabled and API key is available
    if openai_whisper and client:
        try:
            with open(f, "rb") as audio_file:
                logging.debug("Sending audio to OpenAI Whisper API...")
                transcription = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="en",
                    temperature=0.0,
                    response_format="text"
                )
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
            'language': 'en',          # Force English language
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

print("Tab over to another window and start speaking.")
print("Text should appear in the window you are working in.")
print("Say \"Stop listening.\" or press CTRL-C to stop.")
say("All systems ready.")

# Show initial idle status indicator
show_idle_status()

messages = [{ "role": "system", "content": "In this conversation between `user:` and `assistant:`, play the role of assistant. Reply as a helpful assistant." },]

def generate_text(prompt: str):
    conversation_length = 9 # try increasing if AI model has a large ctx window
    global chatting, messages, gpt_key, gem_key
    messages.append({"role": "user", "content": prompt})
    completion = ""
    
    # Show processing status for AI generation
    if show_status:
        print(f"{bs}{processing_color}[PROCESSING]{reset_color} Generating AI response...", end="", flush=True)
    
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
        print(f"{bs}{completion}")
        # handle queries for more information
        if "more information?" in completion or \
            "It sounds like" in completion or \
            "It seems like" in completion or \
            "you tell me" in completion or \
            "Could you please" in completion or \
            "a large language model" in completion or \
            completion == "< nooutput >":
            say("Sorry, I didn't catch that. Can you give me more information, please?")
            chatting = False # allow dictation into the prompt box
            response = pyautogui.prompt("More information, please.",
            "Please clarify.", prompt)
            # on user cancel, stop AI chat & resume dictation
            if not response: return None
            # otherwise, process the new query
            chatting = True
            return generate_text(response)
        pyautogui.write(completion)
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
    while True:
        try:
            # transcribe audio from queue
            if f := audio_queue.get():
                txt = gettext(f)
                # delete temporary audio file
                try: os.remove(f)
                except Exception: pass
                if not txt: continue
                # filter space at beginning of lines
                txt = re.sub(r"(^|\n)\s", r"\1", txt)
                # print messages [BLANK_AUDIO], (swoosh), *barking*
                if re.search(r"[\(\[\*]", txt):
                    print(bs + txt.strip())
                    # filter it out
                    txt = re.sub(r'[\*\[\(][^\]\)]*[\]\)\*]*\s*$', '', txt)
                if txt == " " or txt == "you " or txt == "Thanks for watching! ":
                    continue # ignoring you
                # get lower-case spoken command string
                lower_case = txt.lower().strip()
                if not lower_case: continue
                shutup() # stop bot from talking
                if match := re.search(r"[^\w\s]$", lower_case):
                    lower_case = lower_case[:match.start()] # remove punctuation
                # strip txt unless we specifically say "new paragraph"
                txt = txt.strip(' \n') + ' '
                print(bs + txt) # print the text

                # see list of actions and hotkeys at top of file :)
                # Go to Website.
                if s:=re.search(r"^(peter|computer).? (go|open|browse|visit|navigate)( up| to| the| website)* [a-zA-Z0-9-]{1,63}(\.[a-zA-Z0-9-]{1,63})+$", lower_case):
                    q = lower_case[s.end():] # get q for command
                    webbrowser.open('https://' + q.strip())
                    continue
                # Stop dictation.
                elif re.search(r"^stop.? (d.ctation|listening).?$", lower_case):
                    say("Shutting down.")
                    break
                elif re.search(r"^paused? (d.ctation|positi.?i?cation).?$", lower_case):
                    listening = False
                    say("okay")
                elif process_actions(lower_case): continue
                if not listening: continue
                elif process_hotkeys(lower_case): continue
                elif len(txt) > 1:
                    pyautogui.write(txt)
            # continue looping every 1/5 second
            else: time.sleep(0.2)
        except KeyboardInterrupt:
            say("Goodbye.")
            break

def record_mp3():
    global listening
    listening = False
    say("Recording audio clip...")
    time.sleep(1)
    rec = delayRecord("audio.mp3")
    rec.start()
    say(f"Recording saved to {rec.file_name}")
    time.sleep(1)
    listening = True

def record_to_queue():
    global record_process
    global running
    while running:
        record_process = delayRecord(tempfile.mktemp()+ '.wav')
        record_process.start()
        audio_queue.put(record_process.file_name)

def discard_input():
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
    shutup()

if __name__ == '__main__':
    record_thread = threading.Thread(target=record_to_queue)
#    os.system("systemctl --user start whisper")
    record_thread.start()
    transcribe()
    quit()
