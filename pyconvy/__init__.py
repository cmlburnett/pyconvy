"""
"""

# System
import configparser
import os
import subprocess
import sys
import time

class Convy:
	# All the root paths to scan and watch for addition of files
	_paths = None

	def __init__(self):
		self._paths = []

	def addpath(self, path):
		path = os.path.abspath(path)
		self._paths.append(path)

	def loop(self, timeout=1.0):
		while True:
			self.scandirs()
			time.sleep(timeout)

	def scandirs(self):
		for p in self._paths:
			print(p)
			subs = os.listdir(p)
			print(subs)
			for sub in subs:
				self._scansubdir(p, sub)

	def _scansubdir(self, root, sub):
		# Read in config
		cfgpath = os.path.join(root, sub, 'convy.cfg')
		c = ConvyConfig(cfgpath)
		print(c)

class ConvyConfig:
	def __init__(self, path):
		self._path = path
	
	def Read(self):
		c = configparser.ConfigParser(cfgpath)

