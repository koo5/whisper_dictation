#!/usr/bin/python
# -*- coding: utf-8 -*-
##
## Copyright 2024 Henry Kroll <nospam@thenerdshow.com>
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
import gi
import sys
import urllib.parse
import logging
import time
# Initialize GStreamer
gi.require_version('Gst', '1.0')
from gi.repository import Gst
pipeline = None
Gst.init(None)
talk_process = None
logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s [%(levelname)s] %(lineno)d %(message)s",
	handlers=[
#		logging.FileHandler('/tmp/mimic_client.log'),
		logging.StreamHandler()
	]
)
def say(text, base_url="http://localhost:59125/api/tts"):
    global pipeline
    # For now, just print the text instead of speaking it
    print(f"[SPEECH]: {text}")
    # Keep pipeline as None to avoid errors in shutup()
    pipeline = None

def shutup():
    global pipeline
    # Skip if pipeline is None
    if pipeline is None:
        return
    
    for element in pipeline.children:
        if isinstance(element, Gst.Element):
            element.set_state(Gst.State.NULL)
    time.sleep(0.2)
    pipeline.send_event(Gst.Event.new_eos())
    time.sleep(0.6)
    pipeline.set_state(Gst.State.NULL)

# Example usage
if __name__ == "__main__":
    say("Hello, this is a test of the text to speech system.")
    time.sleep(1)
    shutup()
