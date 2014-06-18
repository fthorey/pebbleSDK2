#! /usr/bin/env python
# encoding: utf-8
# WARNING! Do not edit! http://waf.googlecode.com/git/docs/wafbook/single.html#_obtaining_the_waf_file

def enable_file_name_c_define():
	from waflib.Tools.c_preproc import c_parser
	orig_c_parser_start=c_parser.start
	def c_parser_start(self,node,env):
		env.append_value('DEFINES','__FILE_NAME__="'+str(node)+'"')
		return orig_c_parser_start(self,node,env)
	c_parser.start=c_parser_start
