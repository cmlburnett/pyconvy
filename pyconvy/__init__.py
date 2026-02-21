"""
pyconvy -- python library for converting video and audio files into other formats.
"""

# System
import configparser
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback

# Try to get pushover library otherwise don't use it
try:
	import pushover
except:
	pushover = None

def StartTime():
	start = datetime.datetime.now()
	start_str = start.strftime("%Y-%m-%d %H:%M:%S.%f")

	return start,start_str

def EndTime(start):
	end = datetime.datetime.now()
	end_str = end.strftime("%Y-%m-%d %H:%M:%S.%f")
	diff = end - start
	diff_str = str(diff)

	return end,end_str, diff,diff_str

class ItemProcessed(Exception):
	"""
	Exception raised when an item is finished.
	This ends the loop of finding items to process, and restarts the scan after a short delay.
	This allows adding new items, changing conversion settings, etc. without having to restart the pyconvy porcess.
	"""
	pass

class Convy:
	"""
	Basic class that handles the processing."
	"""

	# All the root paths to scan and watch for addition of files
	_paths = None

	def __init__(self):
		self._paths = []

	def addpath(self, path):
		path = os.path.abspath(path)
		self._paths.append(path)

	def loop(self, timeout=1.0):
		while True:
			dirs = self.scandirs()
			self.processdirs(dirs)
			time.sleep(timeout)

	def scandirs(self):
		validdirs = []

		for p in self._paths:
			if not os.path.isdir(p):
				raise Exception("Added path '%s' that is not a directory" % p)

			# Check root directory here
			ret = self._scansubdir(p, None)
			if ret is None:
				raise Exception("Added path '%s' that is not valid" % p)
			validdirs.append(ret)

		return validdirs

	def _scansubdir(self, root, parent):
		"""
		Check if directory is valid to process.
		"""

		# Read in config
		cfgpath = os.path.join(root, 'convy.cfg')
		if not os.path.exists(cfgpath):
			return None

		c = ConvyConfig(cfgpath, parent)
		c.Read()

		if c.IsMainModeSubdir:
			for sub in c.Directories:
				subp = os.path.join(root, sub)
				subc = self._scansubdir(subp, c)
				if subc is not None:
					c.AddSubDirectory(subc)

		return c

	def processdirs(self, dirs):
		for c in dirs:
			try:
				c.Process()
			except ItemProcessed:
				return
			except:
				# Re raise as not what expected
				raise

class ConvyConfig:
	"""
	Processes a config file and actually processing videos based on nested configuration files.
	"""

	VALID_MODES = ['subdir', 'movie', 'tv', 'soundtrack']
	VALID_RESOLUTIONS = ['sd', 'br', '4k']

	def __init__(self, path, parent):
		print('Config for path %s' % path)
		self._path = path
		self._dirpath, self._filename = os.path.split(self._path)

		self._parent = parent
		self._children = []
		self._items = []

	@property
	def Path(self): return self._path

	@property
	def Filename(self): return self._filename

	@property
	def DirPath(self): return self._dirpath

	@property
	def Config(self): return self._cfg

	@property
	def Parent(self): return self._parent

	@property
	def MainMode(self): return self.Config['main']['mode']

	@property
	def IsMainModeSubdir(self): return self.MainMode.lower() == 'subdir'
	@property
	def IsMainModeMovie(self): return self.MainMode.lower() == 'movie'
	@property
	def IsMainModeTV(self): return self.MainMode.lower() == 'tv'
	@property
	def IsMainModeSoundtrack(self): return self.MainMode.lower() == 'soundtrack'

	@property
	def Directories(self):
		return [_[1] for _ in self._items if _[0] == 'd']

	def AddSubDirectory(self, subc):
		"""
		Add a child config for subdir mode.
		"""

		self._children.append(subc)

	def Read(self):
		"""
		Read in the config and check that it's ok
		"""

		self._cfg = configparser.ConfigParser()
		self.Config.read(self.Path)

		if 'main' not in self.Config.sections():
			raise ValueError("In config '%s', no [main] section found" % self.Path)

		if 'mode' not in self.Config['main']:
			raise ValueError("In config '%s', [main].mode is not set" % self.Path)

		if self.Config['main']['mode'].lower() not in __class__.VALID_MODES:
			raise ValueError("In config '%s', [main].mode '%s' is not recognized" % (self.Path, self.Config['main']['mode']))

		for sub in os.listdir(self.DirPath):
			# Don't need to read itself
			if sub == self.Filename:
				continue

			subp = os.path.join(self.DirPath, sub)

			# Check if dot file so it can be ignored
			# Could add to the itmes list but I don't see reason at this time
			dotstart = sub[0] == '.'
			if dotstart:
				continue

			if os.path.isdir(subp):
				self._items.append( ('d', sub, subp) )
			elif os.path.isfile(subp):
				self._items.append( ('f', sub, subp) )

		for sect in self.Config.sections():
			if sect == 'main': continue

			if sect.startswith('settings-'):
				if 'res' not in self.Config[sect]:
					raise ValueError("In config '%s', settings section '%s' does not have a res key to indicate resolution" % (self.Path, sect))

				# TODO: check av, bv, aspectratio, etc for sanity

				pass

	def Process(self):
		"""
		Process the directory based on the configuration file present.
		"""

		print("Processing %s" % self.Path)
		if self.IsMainModeSubdir:
			for subc in self._children:
				subc.Process()

		elif self.IsMainModeMovie or self.IsMainModeTV:
			for item in self._items:
				done = os.path.split(item[2])[0] + '/.' + os.path.split(item[2])[1]
				if os.path.exists(done):
					print("Already done: %s" % item[2])
					continue

				if self.IsMainModeMovie:
					self.ProcessMovie(item[2])
				elif self.IsMainModeTV:
					self.ProcessTV(item[2])
				else:
					raise NotImplementedError("Should not reach this")

				end = datetime.datetime.now()
				end_str = end.strftime("%Y-%m-%d %H:%M:%S.%f")

				# Mark
				with open(done, 'w') as f:
					f.write("Completed item %s\n\n" % item[2])
					f.write("End: %s\n" % end_str)

	def ProcessMovie(self, path):
		"""
		Process the directory @path as a movie.
		Expects a file named after the directory to be the feature film and everything else is a special feature.
		"""

		name = os.path.split(path)[1]
		print("Processing Movie '%s' (%s)" % (name, path))

		items = os.listdir(path)
		items = VideoHelp.FilterFilesForVideos(items)
		print("%d items found" % len(items))
		for item in items:
			subp = os.path.join(path, item)

			if os.path.isfile(subp):
				if item.startswith(name):
					multi = self.Config['feature']['multipleresolution'].lower() == 'true'
				else:
					multi = self.Config['special']['multipleresolution'].lower() == 'true'

				# Truncated, so skip it
				if os.path.getsize(subp) == 0:
					print("Skipping, item %s has zero file size" % subp)
					continue

				w,h = VideoHelp.GetResolution(subp)
				res = VideoHelp.GuessResolution(w,h)

				settings = {
					'resolution': res,
					'width': w,
					'height': h,
				}

				if multi:
					sets = []

					if res == '4k':
						for res in ('4k', '1k', 'hd', 'sd'):
							s = dict(settings)

							s['resolution'] = res
							self.GetSettings(s)
							sets.append(s)
					elif res == '1k':
						for res in ('1k', 'hd', 'sd'):
							s = dict(settings)

							s['resolution'] = res
							self.GetSettings(s)
							sets.append(s)
					elif res == 'hd':
						for res in ('hd', 'sd'):
							s = dict(settings)

							s['resolution'] = res
							self.GetSettings(settings)
							sets.append(s)

					elif res == 'sd':
						self.GetSettings(settings)
						sets.append(settings)
					else:
						raise NotImplementedError("Shouldn't reach this")

					self.ProcessVideo(name, subp, *sets)
				else:
					# Single resolution
					self.GetSettings(settings)

					self.ProcessVideo(name, subp, settings)

				# If nothing was processed, control will return
				# If something was processed, it throws an ItemProcessed exception which control is not returned to this point

				# Just slow things a bit to avoid hammering notifications if something goes awry
				time.sleep(5)

	def ProcessTV(self, path):
		"""
		Process the directory @path as a TV series.
		Expects a bunch of folders, one per seasons, with a bunch of files inside ofit that are the episodes.
		Inside the season can be subdirectories of special features.
		Naming format for episodes is "SHOW - S__E__ - EPISODE TITLE".
		"""

		name = os.path.split(path)[1]
		print("Processing TV Series '%s' (%s)" % (name, path))

		# Get a list of all seasons
		seasons = os.listdir(path)

		# Get dot files to skip seasons already processed
		dots = [_ for _ in seasons if _[0] == '.']
		seasons = [_ for _ in seasons if os.path.isdir(os.path.join(path,_))]
		for season in seasons:
			print("\tSeason: %s" % season)

		for season in seasons:
			if '.'+season in dots:
				print("Already done season '%s' of '%s'" % (season, name))
			else:
				# Process the season
				self._ProcessTV_Season(path, name, season)

				# Skip season next iteration as its done
				print("Finished season '%s' of '%s'" % (season, name))
				with open(os.path.join(path, '.'+season), 'w'):
					print("\n")

	def _ProcessTV_Season(self, path, name, season):
		"""
		Process a TV season.
		"""

		# Get full path of the season
		fpath = os.path.join(path, season)

		# Split directories from episodes
		items = os.listdir(fpath)
		specialdirs = [_ for _ in items if os.path.isdir(os.path.join(fpath,_))]
		episodes = [_ for _ in items if os.path.isfile(os.path.join(fpath,_))]
		del items

		episodes = VideoHelp.FilterFilesForVideos(episodes)
		for ep in episodes:
			print("\t\tEp: %s" % ep)
		for specialdir in specialdirs:
			print("\t\tSpecial Dir: %s" % specialdir)
			spath = os.path.join(fpath, specialdir)
			specials = os.listdir(spath)
			specials = VideoHelp.FilterFilesForVideos(specials)

			for special in specials:
				print("\t\t\tSpecial: %s" % special)

		# Process episodes first
		for episode in episodes:
			self._ProcessTV_SeasonEpisode(path, name, season, episode)

		# iterate through special directories
		for specialdir in specialdirs:
			spath = os.path.join(fpath, specialdir)
			specials = os.listdir(spath)
			specials = VideoHelp.FilterFilesForVideos(specials)

			for special in specials:
				self._ProcessTV_SeasonSpecial(path, name, season, specialdir, special)

	def _ProcessTV_SeasonEpisode(self, path, name, season, episode):
		# Form full paths
		spath = os.path.join(path, season)
		epath = os.path.join(path, season, episode)

		print("Processing TV Episodes %s" % epath)

		if os.path.getsize(epath) == 0:
			print("Skipping, item %s has zero file size" % epath)
			return

		w,h = VideoHelp.GetResolution(epath)
		res = VideoHelp.GuessResolution(w,h)

		settings = {
			'resolution': res,
			'width': w,
			'height': h,
		}

		multi = self.Config['episode']['multipleresolution'].lower() == 'true'
		if multi:
			sets = []

			if res == '4k':
				for res in ('4k', '1k', 'hd', 'sd'):
					s = dict(settings)

					s['resolution'] = res
					self.GetSettings(s)
					sets.append(s)
			elif res == '1k':
				for res in ('1k', 'hd', 'sd'):
					s = dict(settings)

					s['resolution'] = res
					self.GetSettings(s)
					sets.append(s)
			elif res == 'hd':
				for res in ('hd', 'sd'):
					s = dict(settings)

					s['resolution'] = res
					self.GetSettings(settings)
					sets.append(s)

			elif res == 'sd':
				self.GetSettings(settings)
				sets.append(settings)
			else:
				raise NotImplementedError("Shouldn't reach this")

			newname = '%s/%s/%s' % (name, season, episode)
			self.ProcessVideo(name, epath, *sets)
		else:
			# Single resolution
			self.GetSettings(settings)

			newname = '%s/%s/%s' % (name, season, episode)
			self.ProcessVideo(name, epath, settings)

		# If nothing was processed, control will return
		# If something was processed, it throws an ItemProcessed exception which control is not returned to this point

		# Just slow things a bit to avoid hammering notifications if something goes awry
		time.sleep(5)

	def _ProcessTV_SeasonSpecial(self, path, name, season, specialdir, special_name):
		spath = os.path.join(path, season)
		ppath = os.path.join(path, season, specialdir)
		fpath = os.path.join(path, season, specialdir, special_name)

		print("Processing TV Special %s" % fpath)

		if os.path.getsize(fpath) == 0:
			print("Skipping, item %s has zero file size" % fpath)
			return

		w,h = VideoHelp.GetResolution(fpath)
		res = VideoHelp.GuessResolution(w,h)

		settings = {
			'resolution': res,
			'width': w,
			'height': h,
		}

		multi = self.Config['special']['multipleresolution'].lower() == 'true'
		if multi:
			sets = []

			if res == '4k':
				for res in ('4k', '1k', 'hd', 'sd'):
					s = dict(settings)

					s['resolution'] = res
					self.GetSettings(s)
					sets.append(s)
			elif res == '1k':
				for res in ('1k', 'hd', 'sd'):
					s = dict(settings)

					s['resolution'] = res
					self.GetSettings(s)
					sets.append(s)
			elif res == 'hd':
				for res in ('hd', 'sd'):
					s = dict(settings)

					s['resolution'] = res
					self.GetSettings(settings)
					sets.append(s)

			elif res == 'sd':
				self.GetSettings(settings)
				sets.append(settings)
			else:
				raise NotImplementedError("Shouldn't reach this")

			newname = '%s/%s/%s/%s' % (name, season, specialdir, special_name)
			self.ProcessVideo(newname, fpath, *sets)
		else:
			# Single resolution
			self.GetSettings(settings)

			newname = '%s/%s/%s/%s' % (name, season, specialdir, special_name)
			self.ProcessVideo(newname, fpath, settings)

		# If nothing was processed, control will return
		# If something was processed, it throws an ItemProcessed exception which control is not returned to this point

		# Just slow things a bit to avoid hammering notifications if something goes awry
		time.sleep(5)

	def GetSettings(self, settings):
		"""
		Updates the dictionary of settings @settings by recursing up the config tree applying them from top down.
		"""

		res = settings['resolution']
		key = 'settings-%s' % res
		basekey = 'settings'

		# Add settings in order of bottom to top
		toapply = []

		c = self
		while c:
			# Get resolution specific settings
			if key in c.Config.sections():
				for k,v in c.Config[key].items():
					toapply.append( (k,v) )

			if basekey in c.Config.sections():
				for k,v in c.Config[basekey].items():
					toapply.append( (k,v) )

			c = c.Parent

		# Flip order to top gets applied first and configs down the tree (this absolutely could overwrite settings)
		toapply.reverse()
		for k,v in toapply:
			settings[k] = v

		return settings

	def ProcessVideo(self, name, path, *lst_settings):
		"""
		Take a video file @path and apply the settings @settings to it to do the conversion.
		"""

		if 'video.passes' not in lst_settings[0]:
			raise NotImplementedError("Not handling single pass conversion yet")

		# Get just the file name
		fname = os.path.split(path)[1]

		# Convert passes to an integer
		passes = int(lst_settings[0]['video.passes'])

		# Do a transcode once per pass
		for i in range(0, passes):
			args = []
			dones = []

			# Aggregate all output files into a single command
			for settings in lst_settings:
				# Form output file location @dest
				# Form dot file to signify file and resolution @done was previously converted
				if settings['output.format'] == 'matroska':
					dest = os.path.splitext(path)[0] + (' %s.mkv' % settings['resolution'])
					done = os.path.split(dest)[0] + '/.' + os.path.split(dest)[1]
				else:
					raise ValueError("For video '%s', unknown output formst '%s'" % (path, settings['output.format']))

				# Already done, skip it
				# Because ItemProcessed is thrown when a file & resolution is done, if multiple resolutions for a given file are to be done
				# The done check will quietly allow other resolutions to be processed
				if os.path.exists(done):
					print("Already done %s of %s" % (settings['resolution'], path))
					continue
				else:
					print("Adding %s of %s" % (settings['resolution'], path))
					dones.append(done)

				# Build command for ffmpeg (this modifies @args and returns the same object)
				VideoHelp.BuildFfmpegCommand(args, path,dest, settings, i+1)

			# All are processed
			if len(dones) == 0:
				return

			start,start_str = StartTime()
			print("Starting %s of %s" % (settings['resolution'], path))

			print(args)
			try:
				# Execute ffmpeg
				subprocess.run(args)
			except:
				end,end_str, diff,diff_str = EndTime(start)

				print(args)
				print("Failed to execute ffmpeg")
				traceback.print_exc()

				# Failed to process, mark dot file so others get processed instead
				for done in dones:
					with open(done, 'w') as f:
						f.write("Failed with exception\n\n")
						f.write("Start: %s\n" % start_str)
						f.write("End: %s\n" % end_str)
						f.write("Delta: %s\n\n" % diff_str)
						f.write(' '.join(args))
						f.write('\n\n')
						traceback.print_exc(file=f)
						f.write('\n\n')

				self.SendNotification("Failed pass %d on item %s and took %s, see dot file for exception" % (i+1, name, diff_str), "Failed %s"%name)

				raise ItemProcessed("Failed pass %d on '%s' but with exception" % (i+1, name))

			# Reaches this point
			end,end_str, diff,diff_str = EndTime(start)

			if i+1 < passes:
				print("Pass %d of %s of %s at %s (took %s)" % (i+1, settings['resolution'], path, end_str, diff_str))

				# Report item is done
				self.SendNotification("Pass %d of %d done on item %s and took %s" % (i+1, passes, name, diff_str), "Pass %d of %s/%s"%(i+1,name,fname))
			else:
				print("Done %s/%s of %s at %s (took %s)" % (settings['resolution'], name,fname, end_str, diff_str))

				# Done, set the dot file so it's not redone
				for done in dones:
					with open(done, 'w') as f:
						f.write("Completed\n\n")
						f.write("Start: %s\n" % start_str)
						f.write("End: %s\n" % end_str)
						f.write("Delta: %s\n\n" % diff_str)
						f.write(' '.join(args))
						f.write('\n\n')

				# Report item is done
				self.SendNotification("Completed item %s and took %s" % (name, diff_str), "Done %s/%s"%(name,fname))

				# Done, reprocess the files
				raise ItemProcessed("Finished '%s'" % path)

	def SendNotification(self, msg, title):
		"""
		Send a notification of an event with Pushover.
		Requires a [pushover] section in a config and user and api keys that match that in ~/.pushoverrc
		"""

		# If not the module then abort
		if not pushover:
			return

		try:
			# Get pushover credentials
			po_user,po_api = self.GetPushoverCredentials()

			# If both are provided, then can send
			if po_user and po_api:
				pushover.Client(user=po_user, api=po_api).send_message(msg, title=title)

		except:
			# Don't let this abort the execution
			print("Exception caught in sending notification")
			traceback.print_exc()

	def GetPushoverCredentials(self):
		"""
		Step through config files and finding the pushover credentials.
		"""

		user = None
		api = None
		if 'pushover' in self.Config.sections():
			if 'user' in self.Config['pushover']:
				user = self.Config['pushover']['user']
			if 'api' in self.Config['pushover']:
				api = self.Config['pushover']['api']

		if self._parent:
			# Check if parent config has credentials
			u,a = self._parent.GetPushoverCredentials()
			# If user and u are None, then it will be None
			# If user or u are not None, then it will be the not None value
			# If user and u are not None, then user will be the value (it takes precedence being from the child config)
			return (user or u, api or a)
		else:
			return (user,api)

class VideoHelp:
	"""
	Simple helper class
	"""

	@staticmethod
	def GetResolution(path):
		args = ['mediainfo', '--Output=JSON', path]
		print(['args', args])
		ret = subprocess.run(args, capture_output=True)
		dat = json.loads(ret.stdout)
		for part in dat['media']['track']:
			if part['@type'] == 'Video':
				w = int(part['Sampled_Width'])
				h = int(part['Sampled_Height'])
				return (w,h)

		raise ValueError("Video file '%s' does not have a resolution" % path)

	@staticmethod
	def FilterFilesForVideos(items):
		"""
		Processed videos include sd/hd/1k/4k the name.
		Exclude .cfg, .py, .txt and assume the rest is video
		"""

		items = [_ for _ in items if not _.startswith('.')]
		items = [_ for _ in items if not _.endswith('.cfg')]
		items = [_ for _ in items if not _.endswith('.py')]
		items = [_ for _ in items if not _.endswith('.txt')]
		items = [_ for _ in items if not os.path.splitext(_)[0].endswith(' sd')]
		items = [_ for _ in items if not os.path.splitext(_)[0].endswith(' hd')]
		items = [_ for _ in items if not os.path.splitext(_)[0].endswith(' 1k')]
		items = [_ for _ in items if not os.path.splitext(_)[0].endswith(' 4k')]
		items.sort()

		return items

	@staticmethod
	def GuessResolution(w,h):
		if (w,h) == (720,480):
			return 'sd'
		elif (w,h) == (1080,720):
			return 'hd'
		elif (w,h) == (1920,1080):
			return '1k'
		elif (w,h) == (4096,2160) or (w,h) == (3840,2160):
			return '4k'
		else:
			raise ValueError("Unknown resolution of video '%s' of %d x %d" % (subp, w, h))

	@staticmethod
	def BuildFfmpegCommand(args, srcfile, destfile, settings, passCnt):
		"""
		Builds the command to supply ffmpeg arguments.
		This is called once per output file with different destfile name and settings.
		On first call, the initial ffmpeg arguments are set in the list.
		"""

		# Initial portion of command
		if len(args) == 0:
			args += ['ffmpeg', '-y', '-loglevel', 'warning', '-i', srcfile]

		# Each output file this will called each time (different @destfile values)

		# Hardware encoding
		if settings['video.codec'] == 'hevc_nvenc':
			args += ['-c:v', settings['video.codec']]
			args += ['-b:v', settings['video.bitrate']]
			args += ['-preset', settings['video.preset']]
			args += ['-rc', 'vbr_hq']
			args += ['-rc-lookahead', '32']
			args += ['-multipass', 'fullres']
			args += ['-spatial_aq', '1']
			args += ['-temporal_aq', '1']
			args += ['-aq-strength', '8']

		# Software
		else:
			args += ['-c:v', settings['video.codec']]
			args += ['-b:v', settings['video.bitrate']]
			args += ['-preset', settings['video.preset']]
			args += ['-x265-params', 'pass=%d'%(i+1) + ":stats=%s" % os.path.join(tempfile.gettempdir(), "x265_2pass-%s-.log" % settings['resolution'])]

		# Generic, map first video and audio streams only
		args += ['-map', '0:v:0']
		args += ['-map', '0:a:0']

		# Any additional parameters
		if 'video.params' in settings:
			args += settings['video.params'].split(' ')

		# Finally out the output format
		args += ['-f', settings['output.format']]

		# If first pass, dump to /dev/null, otherwise to intended target file name
		if passCnt == 1:
			args.append(os.devnull)
		else:
			args.append(destfile)

		# Also return but note that this object is modified in place so
		#   args += VideoHelp.BuildFfmpegCommand(args, ....)
		#        ^^
		# is wrong
		return args

