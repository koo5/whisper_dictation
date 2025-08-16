#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Persistent audio recording with continuous pipeline
No device disconnection between recordings
"""

import gi
import os
import sys
import time
import math
import logging
import threading
import queue
import tempfile
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

# Initialize GStreamer
Gst.init(None)

class PersistentAudioRecorder:
    def __init__(self, threshold=-30, stop_after=2.2, ignore=0.3, preroll=0.6):
        self.threshold = threshold
        self.stop_after = stop_after
        self.ignore = ignore
        self.preroll = preroll
        
        # Audio queue for completed segments
        self.audio_queue = queue.Queue()
        
        # Recording state
        self.recording = False
        self.quiet_timer = self.sound_timer = time.time()
        self.current_segment = None
        self.segment_count = 0
        
        # Threading
        self.running = True
        self.loop = None
        self.bus = None
        
        # Create persistent pipeline
        self._create_pipeline()
        
    def _create_pipeline(self):
        """Create the persistent GStreamer pipeline"""
        # Create pipeline with tee to split audio stream
        # One branch goes to level detection, other to appsink for buffering
        self.pipeline = Gst.parse_launch(
            "autoaudiosrc ! "
            "audio/x-raw,rate=16000,channels=1,format=S16LE ! "
            "tee name=t ! "
            "queue ! level name=level_element interval=100000000 ! fakesink "
            "t. ! queue ! valve name=recording_valve drop=true ! "
            "appsink name=appsink emit-signals=true max-buffers=1000"
        )
        
        self.valve = self.pipeline.get_by_name('recording_valve')
        self.appsink = self.pipeline.get_by_name('appsink')
        
        # Connect to appsink signals
        self.appsink.connect('new-sample', self._on_new_sample)
        
        # Audio buffer for current recording
        self.audio_buffer = []
        
        # Set up bus for level monitoring
        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect('message::element', self._monitor_levels)
        self.bus.connect('message', self._on_bus_message)
        
    def _on_new_sample(self, appsink):
        """Handle new audio sample from appsink"""
        sample = appsink.emit('pull-sample')
        if sample:
            buffer = sample.get_buffer()
            self.audio_buffer.append(buffer)
        return Gst.FlowReturn.OK
        
    def _monitor_levels(self, bus, message):
        """Monitor audio levels for voice activity detection"""
        if not message.get_structure() or message.get_structure().get_name() != 'level':
            return
            
        rms = message.get_structure().get_value('rms')[0]
        if math.isnan(rms):
            return
            
        # Debug: log audio levels periodically
        if hasattr(self, '_level_count'):
            self._level_count += 1
        else:
            self._level_count = 1
            
        if self._level_count % 50 == 0:  # Every ~5 seconds at 10Hz
            logging.debug(f"Audio level: {rms:.1f} dB (threshold: {self.threshold})")
            
        reset = time.time()
        seconds_of_quiet = reset - self.quiet_timer
        seconds_of_sound = reset - self.sound_timer
        
        # Voice activity detection
        if rms > self.threshold:
            if self.ignore < seconds_of_sound and not self.recording:
                self._start_segment_recording()
            self.quiet_timer = reset
        else:
            if self.recording and self.stop_after < seconds_of_quiet:
                self._stop_segment_recording()
            elif not self.recording:
                self.sound_timer = reset
                
    def _start_segment_recording(self):
        """Start recording a new audio segment"""
        logging.debug("Starting audio segment recording")
        self.recording = True
        self.segment_count += 1
        
        # Clear buffer for new recording
        self.audio_buffer = []
        
        # Open the valve to start recording
        self.valve.set_property("drop", False)
        
    def _stop_segment_recording(self):
        """Stop recording current segment and queue it"""
        logging.debug("Stopping audio segment recording")
        self.recording = False
        
        # Close the valve to stop recording
        self.valve.set_property("drop", True)
        
        # Save buffered audio to file
        if self.audio_buffer:
            segment_file = f"/tmp/audio_segment_{self.segment_count:05d}.wav"
            if self._save_buffer_to_file(segment_file):
                self.audio_queue.put(segment_file)
                logging.debug(f"Queued audio segment: {segment_file}")
            
    def _save_buffer_to_file(self, filename):
        """Save audio buffer to WAV file"""
        try:
            import wave
            import struct
            
            # WAV file parameters
            sample_rate = 16000
            channels = 1
            sample_width = 2  # 16-bit
            
            with wave.open(filename, 'wb') as wav_file:
                wav_file.setnchannels(channels)
                wav_file.setsampwidth(sample_width)
                wav_file.setframerate(sample_rate)
                
                # Convert GStreamer buffers to audio data
                for buffer in self.audio_buffer:
                    success, map_info = buffer.map(Gst.MapFlags.READ)
                    if success:
                        wav_file.writeframes(map_info.data)
                        buffer.unmap(map_info)
                        
            logging.debug(f"Saved {len(self.audio_buffer)} buffers to {filename}")
            return True
            
        except Exception as e:
            logging.error(f"Error saving audio buffer: {e}")
            return False
        
    def _on_bus_message(self, bus, message):
        """Handle bus messages"""
        if message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logging.error(f"GStreamer error: {err}, {debug}")
            self.stop()
        elif message.type == Gst.MessageType.EOS:
            logging.debug("EOS received")
            self.stop()
            
    def start(self):
        """Start the persistent audio recording"""
        logging.debug("Starting persistent audio recorder")
        
        # Start pipeline
        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            logging.error("Failed to start pipeline")
            return False
        elif ret == Gst.StateChangeReturn.ASYNC:
            logging.debug("Pipeline starting asynchronously")
        else:
            logging.debug("Pipeline started successfully")
            
        # Start main loop in separate thread
        self.loop_thread = threading.Thread(target=self._run_loop)
        self.loop_thread.daemon = True
        self.loop_thread.start()
        
        logging.debug("Persistent recorder initialized and running")
        return True
        
    def _run_loop(self):
        """Run the GLib main loop"""
        try:
            self.loop = GLib.MainLoop()
            self.loop.run()
        except Exception as e:
            logging.error(f"Main loop error: {e}")
            
    def get_audio_segment(self, timeout=5.0):
        """Get next available audio segment"""
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None
            
    def stop(self):
        """Stop the persistent recorder"""
        logging.debug("Stopping persistent audio recorder")
        self.running = False
        
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            
        if self.bus:
            self.bus.remove_signal_watch()
            
        if self.loop:
            self.loop.quit()
            
        # Clean up any remaining temp files
        try:
            while True:
                segment = self.audio_queue.get_nowait()
                if os.path.exists(segment):
                    os.remove(segment)
        except queue.Empty:
            pass