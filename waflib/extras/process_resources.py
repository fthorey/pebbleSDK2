#! /usr/bin/env python
# encoding: utf-8
# WARNING! Do not edit! http://waf.googlecode.com/git/docs/wafbook/single.html#_obtaining_the_waf_file

import json
import os,sys
import time
import re
import waflib
def gen_resource_deps(bld,resources_dict,resources_path_node,output_pack_node,output_id_header_node,resource_header_path,tools_path,is_system=False,font_key_header_node=None,font_key_table_node=None,font_key_include_path=None,timestamp=None):
	bitmap_script=tools_path.find_node('bitmapgen.py')
	font_script=tools_path.find_node('font/fontgen.py')
	pack_entries=[]
	font_keys=[]

	def deploy_generator(entry):
		res_type=entry["type"]
		def_name=entry["name"]
		input_file=str(entry["file"])
		input_node=resources_path_node.find_node(input_file)
		if input_node is None:
			bld.fatal("Cound not find %s resource <%s>"%(res_type,input_file))
		if res_type=="raw":
			output_node=resources_path_node.get_bld().make_node(input_file)
			pack_entries.append((output_node,def_name))
			bld(rule="cp ${SRC} ${TGT}",source=input_node,target=output_node)
		elif res_type=="png":
			output_pbi=resources_path_node.get_bld().make_node(input_file+'.pbi')
			pack_entries.append((output_pbi,def_name))
			bld(rule="python '{}' pbi '{}' '{}'".format(bitmap_script.abspath(),input_node.abspath(),output_pbi.abspath()),source=[input_node,bitmap_script],target=output_pbi)

		elif res_type=="png-trans":
			output_white_pbi=resources_path_node.get_bld().make_node(input_file+'.white.pbi')
			output_black_pbi=resources_path_node.get_bld().make_node(input_file+'.black.pbi')
			pack_entries.append((output_white_pbi,def_name+"_WHITE"))
			pack_entries.append((output_black_pbi,def_name+"_BLACK"))
			bld(rule="python '{}' white_trans_pbi '{}' '{}'".format(bitmap_script.abspath(),input_node.abspath(),output_white_pbi.abspath()),source=[input_node,bitmap_script],target=output_white_pbi)
			bld(rule="python '{}' black_trans_pbi '{}' '{}'".format(bitmap_script.abspath(),input_node.abspath(),output_black_pbi.abspath()),source=[input_node,bitmap_script],target=output_black_pbi)

		elif res_type=="font":
			output_pfo=resources_path_node.get_bld().make_node(input_file+'.'+str(def_name)+'.pfo')
			m=re.search('([0-9]+)',def_name)
			if m==None:
				if def_name!='FONT_FALLBACK':
					raise ValueError('Font {0}: no height found in def name''\n'.format(self.def_name))
				height=14
			else:
				height=int(m.group(0))
			pack_entries.append((output_pfo,def_name))
			font_keys.append(def_name)
			if'trackingAdjust'in entry:
				trackingAdjustArg='--tracking %i'%entry['trackingAdjust']
			else:
				trackingAdjustArg=''
			if'characterRegex'in entry:
				characterRegexArg='--filter "%s"'%(entry['characterRegex'].encode('utf8'))
			else:
				characterRegexArg=''
			bld(rule="python '{}' pfo {} {} {} '{}' '{}'".format(font_script.abspath(),height,trackingAdjustArg,characterRegexArg,input_node.abspath(),output_pfo.abspath()),source=[input_node,font_script],target=output_pfo)
		else:
			waflib.Logs.error("Error Generating Resources: File: "+input_file+" has specified invalid type: "+res_type)
			waflib.Logs.error("Must be one of (raw, png, png-trans, font)")
			raise waflib.Errors.WafError("Generating resources failed")

	if timestamp==None:
		timestamp=int(time.time())

	for res in resources_dict["media"]:
		deploy_generator(res)

	def create_node_with_suffix(node,suffix):
		return node.parent.find_or_declare(node.name+suffix)

	manifest_node=create_node_with_suffix(output_pack_node,'.manifest')
	table_node=create_node_with_suffix(output_pack_node,'.table')
	data_node=create_node_with_suffix(output_pack_node,'.data')
	md_script=tools_path.find_node('pbpack_meta_data.py')
	resource_code_script=tools_path.find_node('generate_resource_code.py')
	data_sources=[]
	cat_string="cat"
	table_string="python '{}' table '{}'".format(md_script.abspath(),table_node.abspath())
	resource_header_string="python '{script}' resource_header ""{version_def_name} '{output_header}' {timestamp} ""'{resource_include}' '{data_file}'".format(script=resource_code_script.abspath(),output_header=output_id_header_node.abspath(),version_def_name='--version_def_name=SYSTEM_RESOURCE_VERSION'if is_system else'',timestamp=timestamp,resource_include=resource_header_path,data_file=data_node.abspath())

	for entry in pack_entries:
		cat_string+=' "%s" '%entry[0].abspath()
		data_sources.append(entry[0])
		table_string+=' "%s" '%entry[0].abspath()
		resource_header_string+=' "%s" '%str(entry[0].abspath())+' "%s" '%str(entry[1])
	cat_string+=' >  "%s" '%data_node.abspath()

	def touch(task):
		open(task.outputs[0].abspath(),'a').close()
	bld(rule=cat_string if pack_entries else touch,source=data_sources,target=data_node)
	bld(rule=table_string,source=data_sources+[md_script],target=table_node)
	bld(rule="python '{script}' manifest '{output_file}' {num_files} ""{timestamp} '{data_chunk_file}'".format(script=md_script.abspath(),output_file=manifest_node.abspath(),num_files=len(pack_entries),timestamp=timestamp,data_chunk_file=data_node.abspath()),source=[data_node,md_script],target=manifest_node)
	bld(rule="cat '{}' '{}' '{}' > '{}'".format(manifest_node.abspath(),table_node.abspath(),data_node.abspath(),output_pack_node.abspath()),source=[manifest_node,table_node,data_node],target=output_pack_node)
	bld(rule=resource_header_string,source=data_sources+[resource_code_script,data_node],target=output_id_header_node,before=['c'])
	if font_key_header_node and font_key_table_node and font_key_include_path:
		key_list_string=" ".join(font_keys)
		bld(rule="python '{script}' font_key_header '{font_key_header}' ""{key_list}".format(script=resource_code_script.abspath(),font_key_header=font_key_header_node.abspath(),key_list=key_list_string),source=resource_code_script,target=font_key_header_node)
		bld(rule="python '{script}' font_key_table '{font_key_table}' "" '{resource_id_header}' '{font_key_header}' {key_list}".format(script=resource_code_script.abspath(),font_key_table=font_key_table_node.abspath(),resource_id_header=output_id_header_node.abspath(),font_key_header=font_key_include_path,key_list=key_list_string),source=resource_code_script,target=font_key_table_node)
