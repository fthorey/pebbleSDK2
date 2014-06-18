#! /usr/bin/env python
# encoding: utf-8
# WARNING! Do not edit! http://waf.googlecode.com/git/docs/wafbook/single.html#_obtaining_the_waf_file

from __future__ import print_function
from struct import pack,unpack
import os
import sys
import zipfile
import argparse
import json
import time
import stm32_crc
import socket
import pprint
MANIFEST_VERSION=1
BUNDLE_PREFIX='bundle'
class MissingFileException(Exception):
	def __init__(self,filename):
		self.filename=filename
def flen(path):
	statinfo=os.stat(path)
	return statinfo.st_size
def stm32crc(path):
	with open(path,'r+b')as f:
		binfile=f.read()
		return stm32_crc.crc32(binfile)&0xFFFFFFFF
def check_paths(*args):
	for path in args:
		if not os.path.exists(path):
			raise MissingFileException(path)
class PebbleBundle(object):
	def __init__(self):
		self.generated_at=int(time.time())
		self.bundle_manifest={'manifestVersion':MANIFEST_VERSION,'generatedAt':self.generated_at,'generatedBy':socket.gethostname(),'debug':{},}
		self.bundle_files=[]
		self.has_firmware=False
		self.has_appinfo=False
		self.has_watchapp=False
		self.has_resources=False
		self.has_jsapp=False
	def add_firmware(self,firmware_path,firmware_type,firmware_timestamp,firmware_hwrev):
		if self.has_firmware:
			raise Exception("Added multiple firmwares to a single bundle")
		if self.has_watchapp:
			raise Exception("Cannot add firmware and watchapp to a single bundle")
		if firmware_type!='normal'and firmware_type!='recovery':
			raise Exception("Invalid firmware type!")
		check_paths(firmware_path)
		self.type='firmware'
		self.bundle_files.append(firmware_path)
		self.bundle_manifest['firmware']={'name':os.path.basename(firmware_path),'type':firmware_type,'timestamp':firmware_timestamp,'hwrev':firmware_hwrev,'size':flen(firmware_path),'crc':stm32crc(firmware_path),}
		self.has_firmware=True
		return True
	def add_resources(self,resources_path,resources_timestamp):
		if self.has_resources:
			raise Exception("Added multiple resource packs to a single bundle")
		check_paths(resources_path)
		self.bundle_files.append(resources_path)
		self.bundle_manifest['resources']={'name':os.path.basename(resources_path),'timestamp':resources_timestamp,'size':flen(resources_path),'crc':stm32crc(resources_path),}
		self.has_resources=True
		return True
	def add_appinfo(self,appinfo_path):
		if self.has_appinfo:
			raise Exception("Added multiple appinfo to a single bundle")
		check_paths(appinfo_path)
		self.bundle_files.append(appinfo_path)
		self.has_appinfo=True
		return True
	def add_watchapp(self,watchapp_path,app_timestamp,sdk_version):
		if self.has_watchapp:
			raise Exception("Added multiple apps to a single bundle")
		if self.has_firmware:
			raise Exception("Cannot add watchapp and firmware to a single bundle")
		self.type='application'
		self.bundle_files.append(watchapp_path)
		self.bundle_manifest['application']={'name':os.path.basename(watchapp_path),'timestamp':app_timestamp,'sdk_version':sdk_version,'size':flen(watchapp_path),'crc':stm32crc(watchapp_path)}
		self.has_watchapp=True
		return True
	def add_jsapp(self,js_files):
		if self.has_jsapp:
			raise Exception("Added multiple js apps to single bundle")
		check_paths(*js_files)
		for f in js_files:
			self.bundle_files.append(f)
		self.has_jsapp=True
		return True
	def write(self,out_path=None,verbose=False):
		if not(self.has_firmware or self.has_watchapp):
			raise Exception("Bundle must contain either a firmware or watchapp")
		self.bundle_manifest['type']=self.type
		if not out_path:
			out_path='pebble-{}-{:d}.pbz'.format(self.type,self.generated_at)
		if verbose:
			pprint.pprint(self.bundle_manifest)
			print('writing bundle to {}'.format(out_path))
		with zipfile.ZipFile(out_path,'w')as z:
			for f in self.bundle_files:
				z.write(f,os.path.basename(f))
			z.writestr('manifest.json',json.dumps(self.bundle_manifest))
		if verbose:
			print('done!')
def check_required_args(opts,*args):
	options=vars(opts)
	for required_arg in args:
		try:
			if not options[required_arg]:
				raise Exception("Missing argument {}".format(required_arg))
		except KeyError:
			raise Exception("Missing argument {}".format(required_arg))
def make_firmware_bundle(firmware,firmware_timestamp,firmware_type,board,resources=None,resources_timestamp=None,outfile=None,verbose=False):
	bundle=PebbleBundle()
	firmware_path=os.path.expanduser(firmware)
	bundle.add_firmware(firmware_path,firmware_type,firmware_timestamp,board)
	if resources:
		resources_path=os.path.expanduser(args.resources)
		bundle.add_resources(resources_path,args.resources_timestamp)
	bundle.write(outfile,verbose)
def make_watchapp_bundle(appinfo,sdk_version,watchapp=None,watchapp_timestamp=None,js_files=None,resources=None,resources_timestamp=None,outfile=None,verbose=False):
	bundle=PebbleBundle()
	appinfo_path=os.path.expanduser(appinfo)
	bundle.add_appinfo(appinfo_path)
	if watchapp:
		watchapp_path=os.path.expanduser(watchapp)
		bundle.add_watchapp(watchapp_path,watchapp_timestamp,sdk_version)
	if js_files is not None and len(js_files)>0:
		bundle.add_jsapp(js_files)
	if resources:
		resources_path=os.path.expanduser(resources)
		bundle.add_resources(resources_path,resources_timestamp)
	bundle.write(outfile,verbose)
def cmd_firmware(args):
	make_firmware_bundle(**vars(args))
def cmd_watchapp(args):
	args.sdk_verison=dict(zip(['major','minor'],[int(x)for x in args.sdk_version.split('.')]))
	make_watchapp_bundle(**vars(args))
if __name__=='__main__':
	parser=argparse.ArgumentParser(description='Create a Pebble bundle.')
	subparsers=parser.add_subparsers(help='commands')
	firmware_parser=subparsers.add_parser('firmware',help='create a Pebble firmware bundle')
	firmware_parser.add_argument('--firmware',help='path to the firmware .bin')
	firmware_parser.add_argument('--firmware-timestamp',help='the (git) timestamp of the firmware',type=int)
	firmware_parser.add_argument('--firmware-type',help='the type of firmware included in the bundle',choices=['normal','recovery'])
	firmware_parser.add_argument('--board',help='the board for which the firmware was built',choices=['bigboard','ev1','ev2'])
	firmware_parser.set_defaults(func=cmd_firmware)
	watchapp_parser=subparsers.add_parser('watchapp',help='create Pebble watchapp bundle')
	watchapp_parser.add_argument('--appinfo',help='path to appinfo.json')
	watchapp_parser.add_argument('--watchapp',help='path to the watchapp .bin')
	watchapp_parser.add_argument('--watchapp-timestamp',help='the (git) timestamp of the app',type=int)
	watchapp_parser.add_argument('--javascript',help='path to the directory with the javascript app files to include')
	watchapp_parser.add_argument('--sdk-version',help='the SDK platform version required to run the app',type=str)
	watchapp_parser.add_argument('--resources',help='path to the generated resource pack')
	watchapp_parser.add_argument('--resources-timestamp',help='the (git) timestamp of the resource pack',type=int)
	watchapp_parser.add_argument("-v","--verbose",help="print additional output",action="store_true")
	watchapp_parser.add_argument("-o","--outfile",help="path to the output file")
	watchapp_parser.set_defaults(func=cmd_watchapp)
	if len(sys.argv)<=1:
		parser.print_help()
		sys.exit(1)
	args=parser.parse_args()
	parser_func=args.func
	del args.func
	parser_func(args)
