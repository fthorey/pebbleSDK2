#! /usr/bin/env python
# encoding: utf-8
# WARNING! Do not edit! http://waf.googlecode.com/git/docs/wafbook/single.html#_obtaining_the_waf_file

import json
import os
import re
import sys
import time
import shutil
import waflib.extras.inject_metadata as inject_metadata
import waflib.extras.ldscript as ldscript
import waflib.extras.mkbundle as mkbundle
import waflib.extras.objcopy as objcopy
import waflib.extras.c_preproc as c_preproc
import waflib.extras.xcode_pebble
from waflib import Logs, Options
from waflib.Task import SKIP_ME, ASK_LATER
from waflib.TaskGen import before_method,feature, after_method
SDK_VERSION={'major':5,'minor':0}
def options(opt):
	opt.load('gcc')
	opt.add_option('-d','--debug',action='store_true', default=False,
                       dest='debug', help='Build in debug mode')

	opt.add_option('-t','--timestamp',dest='timestamp',
                       help="Use a specific timestamp to label this package \
                       (ie, your repository's last commit time), defaults to time of build")

	opt.add_option('--pebble-sdk', action='store', default='',
                       help = 'Set pebble SDK path', dest='pebblesdk')

	opt.add_option('--arm-toolchain-path', action='store', default='',
                       help = 'Set pebble ARM toolchain path', dest='armpath')

def configure(conf):
	conf.load('python')

        arm_path = []
        try:
                path = os.path.abspath("{}{}{}{}{}".format(Options.options.pebblesdk, os.sep, 'arm-cs-tools', os.sep, 'bin'))
                os.stat(path)
                arm_path.append(path)
        except:
                if Options.options.armpath != '':
                        try:
                                path = Options.options.armpath
                                os.stat(os.path.abspath(path))
                                arm_path.append(os.path.abspath("{}{}{}".format(path, os.sep, 'bin')))
                        except:
                                pass
        if arm_path is not []: os.environ['PATH'] += os.pathsep + os.pathsep.join(arm_path)

	CROSS_COMPILE_PREFIX='arm-none-eabi-'
	conf.env.AS=CROSS_COMPILE_PREFIX+'gcc'
	conf.env.AR=CROSS_COMPILE_PREFIX+'ar'
	conf.env.CC=CROSS_COMPILE_PREFIX+'gcc'
	conf.env.LD=CROSS_COMPILE_PREFIX+'ld'
	conf.env.SIZE=CROSS_COMPILE_PREFIX+'size'
	optimize_flag='-Os'
	conf.load('gcc')
	conf.env.CFLAGS=['-std=c99','-mcpu=cortex-m3','-mthumb','-ffunction-sections','-fdata-sections','-g',optimize_flag]
	c_warnings=['-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-error=unused-function','-Wno-error=unused-variable']
	conf.env.append_value('CFLAGS',c_warnings)
	conf.env.LINKFLAGS=['-mcpu=cortex-m3','-mthumb','-Wl,--gc-sections','-Wl,--warn-common',optimize_flag]
	conf.env.SHLIB_MARKER=None
	conf.env.STLIB_MARKER=None
	if not conf.options.debug:
		conf.env.append_value('DEFINES','RELEASE')
	else:
		print"Debug enabled"

        if conf.options.pebblesdk != '':
                pebble_sdk_file = os.path.abspath("{}{}Pebble".format(Options.options.pebblesdk, os.sep))
                try:
                        os.stat(pebble_sdk_file)
                        pebble_sdk = conf.root.find_dir(os.path.abspath(pebble_sdk_file))
                except:
                        pebble_sdk=conf.root.find_dir(os.path.dirname(__file__)).parent.parent.parent
        else:
                pebble_sdk=conf.root.find_dir(os.path.dirname(__file__)).parent.parent.parent

	if pebble_sdk is None:
		conf.fatal("Unable to find Pebble SDK!\n"+"Please make sure you are running waf directly from your SDK or provide a valid SDK path.")

	sdk_check_nodes=['lib/libpebble.a','pebble_app.ld','tools','include','include/pebble.h']
	for n in sdk_check_nodes:
		if pebble_sdk.find_node(n) is None:
                        conf.fatal("Invalid SDK - Could not find {}".format(n))
	print"Found Pebble SDK in\t\t\t : {}".format(pebble_sdk.abspath())
	conf.env.PEBBLE_SDK=pebble_sdk.abspath()

@feature('appinfo')
def init_appinfo(self):
        self.appinfo_json_node = getattr(self, 'jsonfile', False)

@feature('appinfo')
@after_method('init_appinfo')
@before_method('process_source')
def gen_files(self):
        # Generate c file
        coutnode = self.appinfo_json_node.change_ext('.auto.c')
        c_tsk = self.create_task('appinfoc', [self.appinfo_json_node], [coutnode])

        # Add c file back to source for future processing
        # if not self.source: self.source = []
        # self.source.append(coutnode)

        # Get some tools
	sdk_folder=self.bld.root.find_dir(self.bld.env['PEBBLE_SDK'])
        tools_path=sdk_folder.find_dir('tools')

        # Generate datapack
        pack_tsk = self.create_task('gendatapack', [self.appinfo_json_node], [])
        # Set some resources
        pack_tsk.resources_path_node = self.bld.srcnode.find_node('resources')
        pack_tsk.resource_id_header_node = self.path.find_or_declare('src/resource_ids.auto.h')
        pack_tsk.output_pack_node = self.path.find_or_declare('app_resources.pbpack')

        # Set some env
        self.env.BITMAPSCRIPT = tools_path.find_node('bitmapgen.py').abspath()
        self.env.FONTSCRIPT = tools_path.find_node('font/fontgen.py').abspath()
	self.env.MDSCRIPT = tools_path.find_node('pbpack_meta_data.py').abspath()
	self.env.RESCODESCRIPT = tools_path.find_node('generate_resource_code.py').abspath()

from waflib import Task
class gendatapack(Task.Task):
        color   = 'PINK'
        quiet   = True

        def scan(self):
                found_lst = []

                with open(self.inputs[0].abspath(),'r')as f:
                        appinfo = json.load(f)
		resources_dict=appinfo['resources']

                # Process appinfo
                for res in resources_dict['media']:
                        res_type=res["type"]
                        input_file=str(res["file"])
                        input_node=self.resources_path_node.find_node(input_file)
                        if input_node is None:
                                self.generator.bld.fatal("Could not find {} resource <{}>"
                                                         .format(res_type,input_file))

                        if res_type in ['raw', 'png', 'png-trans', 'font']:
                                found_lst.append(input_node)
                        else:
                                waflib.Logs.error("Error Generating Resources: File: " + \
                                                  input_file+" has specified invalid type: " + res_type)
                                waflib.Logs.error("Must be one of (raw, png, png-trans, font)")
                                raise waflib.Errors.WafError("Generating resources failed")

                return (found_lst, [])

        def run(self):
                self.more_tasks = []

                pack_entries = []
                pbpack_tasks = []

                with open(self.inputs[0].abspath(),'r')as f:
                        appinfo = json.load(f)
		resources_dict=appinfo['resources']

                # Process appinfo
                for res in resources_dict['media']:

                        res_type = res["type"]
                        def_name = res["name"]
                        input_file = str(res["file"])
                        input_node = self.resources_path_node.find_node(input_file)

                        # Process .raw files -> .raw
                        if res_type == 'raw':
                                pack_entries.append((input_node, def_name))
                                # -> No prcess needed

                        # Process png files -> .png.pbi
                        elif res_type == 'png':
                                output_node = input_node.change_ext('.png.pbi')
                                pack_entries.append((output_node, def_name))
                                pbi_tsk = self.generator.create_task('procpng',
                                                                     [input_node],
                                                                     [output_node])
                                pbpack_tasks.append(pbi_tsk)
                                self.more_tasks.append(pbi_tsk)

                        # Process png-trans files -> .png.white.pbi / .png.black.pbi
                        elif res_type == "png-trans":
                                for color in ['white', 'black']:
                                        output_node = input_node.change_ext(".png.{}.pbi".format(color))
                                        pack_entries.append((output_node,"{}_{}".format(def_name, color.upper())))
                                        pbi_tsk = self.generator.create_task('procpng',
                                                                             [input_node],
                                                                             [output_node])
                                        pbpack_tasks.append(pbi_tsk)
                                        self.more_tasks.append(pbi_tsk)

                        # Process font files -> .def_name.pfo
                        elif res_type == "font":
                                output_node = input_node.change_ext('.' + str(def_name) + '.pfo')
                                pack_entries.append((output_node, def_name))
                                font_tsk = self.generator.create_task('procfont',
                                                                      [input_node],
                                                                      [output_node])
                                pbpack_tasks.append(font_tsk)

                                m = re.search('([0-9]+)', def_name)
                                if m == None:
                                        if def_name != 'FONT_FALLBACK':
                                                raise ValueError('Font {0}: no height found in def name''\n'
                                                                 .format(self.def_name))
                                        height = 14
                                else:
                                        height = int(m.group(0))

                                if 'trackingAdjust' in res:
                                        trackingAdjustArg = '--tracking %i' % res['trackingAdjust']
                                else:
                                        trackingAdjustArg = ''

                                if 'characterRegex' in res:
                                        characterRegexArg = '--filter "%s"' % (res['characterRegex']
                                                                               .encode('utf8'))
                                else:
                                        characterRegexArg=''

                                font_tsk.env.append_value('FONTHEIGHT', [str(height)])
                                font_tsk.env.append_value('TRACKINGARG', [trackingAdjustArg])
                                font_tsk.env.append_value('REGEXPARG', [characterRegexArg])
                                self.more_tasks.append(font_tsk)

                        # File extension not handled
                        else:
                                raise waflib.Errors.WafError("Generating resources failed")

                manifest_node = self.output_pack_node.change_ext('.pbpack.manifest')
                table_node = self.output_pack_node.change_ext('.pbpack.table')
                data_node = self.output_pack_node.change_ext('.pbpack.data')

                # Generate .pbpack.data
                pbdata_tsk = self.generator.create_task('mergedata',
                                                        [entry[0] for entry in pack_entries],
                                                        [data_node])
                for tsk in pbpack_tasks: pbdata_tsk.set_run_after(tsk)
                self.more_tasks.append(pbdata_tsk)

                # Generate .pbpack.table
                pbtable_tsk = self.generator.create_task('mergetable',
                                                        [entry[0] for entry in pack_entries],
                                                        [table_node])
                for tsk in pbpack_tasks: pbtable_tsk.set_run_after(tsk)
                self.more_tasks.append(pbtable_tsk)

                timestamp = int(time.time())

                # Generate .pbpack.manifest
                manifest_tsk = self.generator.create_task('manifest',
                                                          [data_node],
                                                          [manifest_node])
                manifest_tsk.env.append_value('NUMFILES', [str(len(pack_entries))])
                manifest_tsk.env.append_value('TIMESTAMP', [str(timestamp)])
                manifest_tsk.set_run_after(pbdata_tsk)
                self.more_tasks.append(manifest_tsk)

                # Generate header
                header_tsk = self.generator.create_task('genheader',
                                                        [data_node] + \
                                                        [entry[0] for entry in pack_entries],
                                                        [self.resource_id_header_node])
                header_tsk.resource_header_path = 'pebble.h'
                header_tsk.version_def_name = '--version_def_name=SYSTEM_RESOURCE_VERSION'
                header_tsk.pack_entries = pack_entries
                header_tsk.timestamp = str(timestamp)
                for tsk in pbpack_tasks: pbtable_tsk.set_run_after(tsk)
                header_tsk.set_run_after(pbdata_tsk)
                self.more_tasks.append(header_tsk)

class pbpack(Task.Task):
        color = 'BLUE'

        def run(self):
                pass

class genheader(Task.Task):
        color = 'BLUE'

        def run(self):
                header_string = '{} {} resource_header {} {} {} {}'.format(self.env.PYTHON[0],
                                                                           self.env.RESCODESCRIPT,
                                                                           self.outputs[0].abspath(),
                                                                           self.timestamp,
                                                                           self.resource_header_path,
                                                                           self.inputs[0])
                for entry, set in zip(self.inputs[1:], self.pack_entries):
                        header_string += ' "%s" '%str(entry.abspath())+' "%s" '%str(set[1])
                return self.exec_command(header_string)

class manifest(Task.Task):
        color = 'BLUE'
        run_str = '${PYTHON} ${MDSCRIPT} manifest ${TGT} ${NUMFILES} ${TIMESTAMP} ${SRC}'

class mergetable(Task.Task):
        color = 'BLUE'

        def run(self):
                table_string="{} {} table {}".format(self.env.PYTHON[0],
                                                     self.env.MDSCRIPT,
                                                     self.outputs[0].abspath())
                for entry in self.inputs:
                        table_string += ' {} '.format(entry.abspath())
                return self.exec_command(table_string)

class mergedata(Task.Task):
        color = 'BLUE'

        def run(self):
                cat_string="cat"
                for entry in self.inputs:
                        cat_string += ' "{}" '.format(entry.abspath())
                cat_string += ' > "{}" '.format(self.outputs[0].abspath())
                return self.exec_command(cat_string)

class copy(Task.Task):
        color = 'BLUE'
        run_str = 'cp ${SRC} ${TGT}'

class procfont(Task.Task):
        color = 'BLUE'
        run_str = '${PYTHON} ${FONTSCRIPT} pfo ${FONTHEIGHT} ${TRACKINGARG} ${REGEXPARG} ${SRC} ${TGT}'

class procpng(Task.Task):
        color = 'BLUE'
        run_str = '${PYTHON} ${BITMAPSCRIPT} pbi ${SRC} ${TGT}'

class appinfoc(Task.Task):
	color   = 'GREEN'

        def run(self):
                import waflib.extras.generate_appinfo as generate_appinfo
                generate_appinfo.generate_appinfo(self.inputs[0].abspath(),
                                                  self.outputs[0].abspath())

# class appinfoh(Task.Task):
# 	"""generate appinfo h file"""
# 	color   = 'GREEN'

#         def run(self):
#                 import waflib.extras.process_resources as process_resources
# 		with open(appinfo_json_node.abspath(),'r')as f:
# 			appinfo=json.load(f)
# 		resources_dict=appinfo['resources']
# 		process_resources.gen_resource_deps(bld,
#                                                     resources_dict=resources_dict,
#                                                     resources_path_node=bld.path.get_src().find_node('resources'),
#                                                     output_pack_node=bld.path.get_bld().make_node('app_resources.pbpack'),
#                                                     output_id_header_node=resource_id_header,resource_header_path="pebble.h",
#                                                     tools_path=sdk_folder.find_dir('tools'))

# 	sdk_folder=bld.root.find_dir(bld.env['PEBBLE_SDK'])

def append_to_attr(self,attr,new_values):
	values=self.to_list(getattr(self,attr,[]))
	values.extend(new_values)
	setattr(self,attr,values)

@feature('c')
@before_method('process_source')
def setup_pebble_c(self):
	sdk_folder=self.bld.root.find_dir(self.bld.env['PEBBLE_SDK'])
	append_to_attr(self,'includes',[sdk_folder.find_dir('include').path_from(self.bld.path),'.','src'])
	append_to_attr(self,'cflags',['-fPIE'])

@feature('cprogram')
@before_method('process_source')
def setup_cprogram(self):
	append_to_attr(self,'linkflags',['-mcpu=cortex-m3','-mthumb','-fPIE'])

# @feature('cprogram_pebble')
# @before_method('process_source')
# def setup_pebble_cprogram(self):
# 	sdk_folder=self.bld.root.find_dir(self.bld.env['PEBBLE_SDK'])
# 	append_to_attr(self,'source',[self.bld.path.get_bld().make_node('appinfo.auto.c')])
# 	append_to_attr(self,'stlibpath',[sdk_folder.find_dir('lib').abspath()])
# 	append_to_attr(self,'stlib',['pebble'])
# 	append_to_attr(self,'linkflags',['-Wl,-Map,pebble-app.map,--emit-relocs'])
# 	setattr(self,'ldscript',sdk_folder.find_node('pebble_app.ld').path_from(self.bld.path))

# @feature('pbl_bundle')
# def make_pbl_bundle(self):
# 	timestamp=self.bld.options.timestamp
# 	pbw_basename='app_'+str(timestamp)if timestamp else self.bld.path.name
# 	if timestamp is None:
# 		timestamp=int(time.time())
# 	elf_file=self.bld.path.get_bld().make_node(getattr(self,'elf'))
# 	if elf_file is None:
# 		raise Exception("Must specify elf argument to pbl_bundle")
# 	raw_bin_file=self.bld.path.get_bld().make_node('pebble-app.raw.bin')
# 	self.bld(rule=objcopy.objcopy_bin,source=elf_file,target=raw_bin_file)
# 	js_nodes=self.to_nodes(getattr(self,'js',[]))
# 	js_files=[x.abspath()for x in js_nodes]
# 	has_jsapp=len(js_nodes)>0
# 	def inject_data_rule(task):
# 		bin_path=task.inputs[0].abspath()
# 		elf_path=task.inputs[1].abspath()
# 		res_path=task.inputs[2].abspath()
# 		tgt_path=task.outputs[0].abspath()
# 		cp_result=task.exec_command('cp "{}" "{}"'.format(bin_path,tgt_path))
# 		if cp_result<0:
# 			from waflib.Errors import BuildError
# 			raise BuildError("Failed to copy %s to %s!"%(bin_path,tgt_path))
# 		inject_metadata.inject_metadata(tgt_path,elf_path,res_path,timestamp,allow_js=has_jsapp)
# 	resources_file=self.bld.path.get_bld().make_node('app_resources.pbpack.data')
# 	bin_file=self.bld.path.get_bld().make_node('pebble-app.bin')
# 	self.bld(rule=inject_data_rule,name='inject-metadata',source=[raw_bin_file,elf_file,resources_file],target=bin_file)
# 	resources_pack=self.bld.path.get_bld().make_node('app_resources.pbpack')
# 	pbz_output=self.bld.path.get_bld().make_node(pbw_basename+'.pbw')
# 	def make_watchapp_bundle(task):
# 		watchapp=task.inputs[0].abspath()
# 		resources=task.inputs[1].abspath()
# 		outfile=task.outputs[0].abspath()
# 		return mkbundle.make_watchapp_bundle(appinfo=self.bld.path.get_src().find_node('appinfo.json').abspath(),js_files=js_files,watchapp=watchapp,watchapp_timestamp=timestamp,sdk_version=SDK_VERSION,resources=resources,resources_timestamp=timestamp,outfile=outfile)
# 	self.bld(rule=make_watchapp_bundle,source=[bin_file,resources_pack]+js_nodes,target=pbz_output)
# 	def report_memory_usage(task):
# 		src_path=task.inputs[0].abspath()
# 		size_output=task.generator.bld.cmd_and_log([task.env.SIZE,src_path],quiet=waflib.Context.BOTH,output=waflib.Context.STDOUT)
# 		text_size,data_size,bss_size=[int(x)for x in size_output.splitlines()[1].split()[:3]]
# 		app_ram_size=data_size+bss_size+text_size
# 		max_app_ram=inject_metadata.MAX_APP_MEMORY_SIZE
# 		free_size=max_app_ram-app_ram_size
# 		Logs.pprint('YELLOW',"Memory usage:\n=============\n""Total app footprint in RAM:     %6u bytes / ~%ukb\n""Free RAM available (heap):      %6u bytes\n"%(app_ram_size,max_app_ram/1024,free_size))
# 	self.bld(rule=report_memory_usage,name='report-memory-usage',source=[elf_file],target=None)

from waflib.Configure import conf
@conf
def pbl_bundle(self,*k,**kw):
	kw['features']='pbl_bundle'
	return self(*k,**kw)
@conf
def pbl_program(self,*k,**kw):
	kw['features']='c cprogram cprogram_pebble'
	return self(*k,**kw)
