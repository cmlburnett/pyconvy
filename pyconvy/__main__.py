
from pyconvy import Convy

# System
import sys

def process(path):
	c = Convy()
	c.addpath(path)
	c.loop()

if __name__ == '__main__':
	if len(sys.argv) == 1:
		process('.')
	else:
		process(sys.argv[1])

