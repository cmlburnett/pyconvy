
from pyconvy import Convy

# System
import os
import sys

def process(path):
	c = Convy()
	args = c.getargs()
	print(args)

	# Assume CWD if none is set
	if len(args.dirs) == 0:
		args.daemon.append('.')

	for _ in args.dirs:
		_ = os.path.abspath(_)
		print("Adding directory to watch: %s" % _)
		c.addpath(_)

	if args.daemon:
		c.daemon_loop()

	elif args.status:
		c.print_status()

	elif args.redo:
		c.redo()

	elif args.move:
		c.move()

	else:
		raise NotImplementedError("Unknown mode, aborting")

if __name__ == '__main__':
	if len(sys.argv) == 1:
		process('.')
	else:
		process(sys.argv[1])

