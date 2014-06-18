#! /usr/bin/env python
# encoding: utf-8
# WARNING! Do not edit! http://waf.googlecode.com/git/docs/wafbook/single.html#_obtaining_the_waf_file

from __future__ import with_statement
from struct import pack,unpack
import os
import os.path
import sys
import time
from subprocess import Popen,PIPE
from shutil import copy2
from binascii import crc32
from struct import pack
import stm32_crc
HEADER_ADDR=0x0
STRUCT_VERSION_ADDR=0x8
SDK_VERSION_ADDR=0xa
APP_VERSION_ADDR=0xc
LOAD_SIZE_ADDR=0xe
OFFSET_ADDR=0x10
CRC_ADDR=0x14
NAME_ADDR=0x18
COMPANY_ADDR=0x38
ICON_RES_ID_ADDR=0x58
JUMP_TABLE_ADDR=0x5c
FLAGS_ADDR=0x60
NUM_RELOC_ENTRIES_ADDR=0x64
UUID_ADDR=0x68
RESOURCE_CRC_ADDR=0x78
RESOURCE_TIMESTAMP_ADDR=0x7c
VIRTUAL_SIZE_ADDR=0x80
STRUCT_SIZE_BYTES=0x82
APP_INFO_STANDARD_APP=(0)
APP_INFO_WATCH_FACE=(1<<0)
APP_INFO_VISIBILITY_HIDDEN=(1<<1)
APP_INFO_VISIBILITY_SHOWN_ON_COMMUNICATION=(1<<2)
APP_INFO_ALLOW_JS=(1<<3)
MAX_APP_BINARY_SIZE=0x10000
MAX_APP_MEMORY_SIZE=24*1024
ENTRY_PT_SYMBOL='main'
JUMP_TABLE_ADDR_SYMBOL='pbl_table_addr'
DEBUG=False
class InvalidBinaryError(Exception):
	pass
cached_nm_output=None
def inject_metadata(target_binary,target_elf,resources_file,timestamp,allow_js=False):
	if target_binary[-4:]!='.bin':
		raise Exception("Invalid filename <%s>! The filename should end in .bin"%target_binary)
	def get_symbol_addr(elf_file,symbol):
		global cached_nm_output
		if not cached_nm_output:
			nm_process=Popen(['arm-none-eabi-nm',elf_file],stdout=PIPE)
			cached_nm_output=nm_process.communicate()[0]
			if not cached_nm_output:
				raise InvalidBinaryError()
			cached_nm_output=[line.split()for line in cached_nm_output.splitlines()]
		for sym in cached_nm_output:
			if symbol==sym[-1]and len(sym)==3:
				return int(sym[0],16)
		raise Exception("Could not locate symbol <%s> in binary! Failed to inject app metadata"%(symbol))
	def get_virtual_size(elf_file):
		readelf_bss_process=Popen("arm-none-eabi-readelf -S '%s'"%elf_file,shell=True,stdout=PIPE)
		readelf_bss_output=readelf_bss_process.communicate()[0]
		last_section_end_addr=0
		for line in readelf_bss_output.splitlines():
			if len(line)<10:
				continue
			line=line[6:]
			columns=line.split()
			if len(columns)<6:
				continue
			if columns[0]=='.bss':
				addr=int(columns[2],16)
				size=int(columns[4],16)
				last_section_end_addr=addr+size
			elif columns[0]=='.data'and last_section_end_addr==0:
				addr=int(columns[2],16)
				size=int(columns[4],16)
				last_section_end_addr=addr+size
		if last_section_end_addr!=0:
			return last_section_end_addr
		sys.stderr.writeline("Failed to parse ELF sections while calculating the virtual size\n")
		sys.stderr.write(readelf_bss_output)
		raise Exception("Failed to parse ELF sections while calculating the virtual size")
	def get_relocate_entries(elf_file):
		entries=[]
		readelf_relocs_process=Popen(['arm-none-eabi-readelf','-r',elf_file],stdout=PIPE)
		readelf_relocs_output=readelf_relocs_process.communicate()[0]
		lines=readelf_relocs_output.splitlines()
		i=0
		reading_section=False
		while i<len(lines):
			if not reading_section:
				if lines[i].startswith("Relocation section '.rel.data"):
					reading_section=True
					i+=1
			else:
				if len(lines[i])==0:
					reading_section=False
				else:
					entries.append(int(lines[i].split(' ')[0],16))
			i+=1
		readelf_relocs_process=Popen(['arm-none-eabi-readelf','--sections',elf_file],stdout=PIPE)
		readelf_relocs_output=readelf_relocs_process.communicate()[0]
		lines=readelf_relocs_output.splitlines()
		for line in lines:
			if'.got'in line and'.got.plt'not in line:
				words=line.split(' ')
				while''in words:
					words.remove('')
				section_label_idx=words.index('.got')
				addr=int(words[section_label_idx+2],16)
				length=int(words[section_label_idx+4],16)
				for i in range(addr,addr+length,4):
					entries.append(i)
				break
		return entries
	try:
		app_entry_address=get_symbol_addr(target_elf,ENTRY_PT_SYMBOL)
	except:
		raise Exception("Missing app entry point! Must be `int main(void) { ... }` ")
	jump_table_address=get_symbol_addr(target_elf,JUMP_TABLE_ADDR_SYMBOL)
	reloc_entries=get_relocate_entries(target_elf)
	statinfo=os.stat(target_binary)
	app_load_size=statinfo.st_size
	with open(resources_file,'r+b')as f:
		resource_crc=stm32_crc.crc32(f.read())
	if DEBUG:
		copy2(target_binary,target_binary+".orig")
	with open(target_binary,'r+b')as f:
		total_app_image_size=app_load_size+(len(reloc_entries)*4)
		if total_app_image_size>MAX_APP_BINARY_SIZE:
			raise Exception("App image size is %u (app %u relocation table %u). Must be smaller than %u bytes"%(total_app_image_size,app_load_size,len(reloc_entries)*4,MAX_APP_BINARY_SIZE))
		def read_value_at_offset(offset,format_str,size):
			f.seek(offset)
			return unpack(format_str,f.read(size))
		app_bin=f.read()
		app_crc=stm32_crc.crc32(app_bin[STRUCT_SIZE_BYTES:])
		[app_flags]=read_value_at_offset(FLAGS_ADDR,'<L',4)
		if allow_js:
			app_flags=app_flags|APP_INFO_ALLOW_JS
		app_virtual_size=get_virtual_size(target_elf)
		struct_changes={'load_size':app_load_size,'entry_point':"0x%08x"%app_entry_address,'symbol_table':"0x%08x"%jump_table_address,'flags':app_flags,'crc':"0x%08x"%app_crc,'num_reloc_entries':"0x%08x"%len(reloc_entries),'resource_crc':"0x%08x"%resource_crc,'timestamp':timestamp,'virtual_size':app_virtual_size}
		def write_value_at_offset(offset,format_str,value):
			f.seek(offset)
			f.write(pack(format_str,value))
		write_value_at_offset(LOAD_SIZE_ADDR,'<H',app_load_size)
		write_value_at_offset(OFFSET_ADDR,'<L',app_entry_address)
		write_value_at_offset(CRC_ADDR,'<L',app_crc)
		write_value_at_offset(RESOURCE_CRC_ADDR,'<L',resource_crc)
		write_value_at_offset(RESOURCE_TIMESTAMP_ADDR,'<L',timestamp)
		write_value_at_offset(JUMP_TABLE_ADDR,'<L',jump_table_address)
		write_value_at_offset(FLAGS_ADDR,'<L',app_flags)
		write_value_at_offset(NUM_RELOC_ENTRIES_ADDR,'<L',len(reloc_entries))
		write_value_at_offset(VIRTUAL_SIZE_ADDR,"<H",app_virtual_size)
		f.seek(app_load_size)
		for entry in reloc_entries:
			f.write(pack('<L',entry))
		f.flush()
	return struct_changes
