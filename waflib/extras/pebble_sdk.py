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
from waflib import Task, Utils
from waflib.Task import TaskBase, SKIP_ME, ASK_LATER
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
        arm_path = ''
        try:
                path = os.path.abspath("{}{}{}{}{}".format(Options.options.pebblesdk, os.sep, 'arm-cs-tools', os.sep, 'bin'))
                os.stat(path)
                arm_path = path
        except:
                if Options.options.armpath != '':
                        try:
                                path = Options.options.armpath
                                os.stat(os.path.abspath(path))
                                arm_path = os.path.abspath("{}{}{}".format(path, os.sep, 'bin'))
                        except:
                                pass

	CROSS_COMPILE_PREFIX = 'arm-none-eabi-'

        if arm_path != '':
                conf.env.AS     = arm_path + os.sep + CROSS_COMPILE_PREFIX+'gcc'
                conf.env.AR     = arm_path + os.sep + CROSS_COMPILE_PREFIX+'ar'
                conf.env.CC     = arm_path + os.sep + CROSS_COMPILE_PREFIX+'gcc'
                conf.env.LD     = arm_path + os.sep + CROSS_COMPILE_PREFIX+'ld'
                conf.env.SIZE   = arm_path + os.sep + CROSS_COMPILE_PREFIX+'size'
                conf.env.OBJCPY = arm_path + os.sep + CROSS_COMPILE_PREFIX+'objcopy'
        else:
                conf.env.AS     = CROSS_COMPILE_PREFIX+'gcc'
                conf.env.AR     = CROSS_COMPILE_PREFIX+'ar'
                conf.env.CC     = CROSS_COMPILE_PREFIX+'gcc'
                conf.env.LD     = CROSS_COMPILE_PREFIX+'ld'
                conf.env.SIZE   = CROSS_COMPILE_PREFIX+'size'
                conf.env.OBJCPY = CROSS_COMPILE_PREFIX+'objcopy'

	conf.load('gcc')

	optimize_flag='-Os'
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

        conf.msg('Checking for Pebble SDK', '{}'.format(pebble_sdk.abspath()))
	conf.env.PEBBLE_SDK = pebble_sdk.abspath()

def build(bld):
        # Don't know if useful or not...
        c_preproc.enable_file_name_c_define()

        appinfo_json_node = bld.path.find_node('appinfo.json')
	if appinfo_json_node is None:
		bld.fatal('Could not find appinfo.json')

        bld(features       = 'appinfo_res',
            name           = 'gen_appinfo_res',
            appinfo        = appinfo_json_node)

        bld(features      = 'datapack',
            name          = 'gen_datapack',
            header_path   = 'pebble.h',
            use           = 'gen_appinfo_res')

        bld(features       = 'appinfo_auto_c',
            name           = 'gen_appinfo_auto_c',
            appinfo        = appinfo_json_node)

class resources(Task.Task):
	color   = 'BLUE'

	def signature(self):
		""" override signature method and add dictionary to hash """
		try: return self.cache_sig
		except AttributeError: pass
		self.m = Utils.md5()
		self.m.update(self.hcode.encode())
		# explicit deps
		self.sig_explicit_deps()
		# env vars
		self.sig_vars()
		#dict
		self.m.update( repr(sorted(self.resources.items())) )
		# implicit deps / scanner results
		if self.scan:
			try:
				self.sig_implicit_deps()
			except Errors.TaskRescan:
				return self.signature()
		ret = self.cache_sig = self.m.digest()
		return ret

@feature('appinfo_res')
def init_appinfo_res(self):
        self.pack_entries = []

        appinfo_json_node = getattr(self, 'appinfo', None)
        with open(appinfo_json_node.abspath(), 'r') as f:
                appinfo = json.load(f)
        self.resources = appinfo['resources']

	sdk_folder = self.bld.root.find_dir(self.bld.env['PEBBLE_SDK'])
        tools_path = sdk_folder.find_dir('tools')

        self.bitmapscript = tools_path.find_node('bitmapgen.py').abspath()
        self.fontscript = tools_path.find_node('font/fontgen.py').abspath()

        self.raw_nodes, self.png_nodes, self.png_trans_nodes, self.font_nodes = [], [], [], []
        self.fonts = {}
        resources_node = self.bld.srcnode.find_node('resources')
        for res in self.resources['media']:
                def_name = res["name"]
                res_type=res["type"]
                input_file=str(res["file"])
                input_node = resources_node.find_node(input_file)
                if input_node is None:
                        self.bld.fatal("Could not find {} resource <{}>"
                                       .format(res_type,input_file))
                else:
                        if res_type == 'raw':
                                self.raw_nodes.append((input_node, def_name))
                        elif res_type == 'png':
                                self.png_nodes.append((input_node, def_name))
                        elif res_type == 'png-trans':
                                self.png_trans_nodes.append((input_node, def_name))
                        elif res_type == 'font':
                                self.font_nodes.append((input_node, def_name))
                                self.fonts[def_name] = {}
                                m = re.search('([0-9]+)', def_name)
                                if m == None:
                                        if def_name!='FONT_FALLBACK':
                                                raise ValueError('Font {0}: no height found in def name''\n'.format(self.def_name))
                                        height = 14
                                else:
                                        height = int(m.group(0))
                                self.fonts[def_name]['height'] = height

                                trackingAdjustArg = ''
                                if 'trackingAdjust'in res:
                                        trackingAdjustArg = '--tracking {}'.format(
                                                res['trackingAdjust'])

                                self.fonts[def_name]['tracking'] = trackingAdjustArg

                                characterRegexArg = ''
                                if 'characterRegex'in res:
                                        characterRegexArg = '--filter "{}"'.format(
                                                res['characterRegex'].encode('utf8'))

                                self.fonts[def_name]['regex'] = characterRegexArg

@feature('appinfo_res')
@after_method('init_appinfo_res')
def process_bpi(self):
        for input_node, def_name in self.png_nodes:
                output_node = input_node.change_ext('.png.pbi')
                self.pack_entries.append((output_node, def_name))
                if not getattr(self, 'dry_run', False):
                        pbi_tsk = self.create_task('genpbi', [input_node], [output_node])
                        pbi_tsk.resources = self.resources
                        pbi_tsk.env.append_value('BITMAPSCRIPT', [self.bitmapscript])

@feature('appinfo_res')
@after_method('process_pbi')
def process_trans_bpi(self):
        for input_node, def_name in self.png_trans_nodes:
                for color in ['white', 'black']:
                        output_node = input_node.change_ext('.png.{}.pbi'.format(color))
                        self.pack_entries.append((output_node,"{}_{}".format(def_name, color.upper())))
                        if not getattr(self, 'dry_run', False):
                                pbi_tsk = self.create_task('genpbi', [input_node], [output_node])
                                pbi_tsk.resources = self.resources
                                pbi_tsk.env.append_value('BITMAPSCRIPT', [self.bitmapscript])

class genpbi(resources):
        color = 'BLUE'
        run_str = '${PYTHON} ${BITMAPSCRIPT} pbi ${SRC} ${TGT}'

@feature('appinfo_res')
@after_method('process_trans_pbi')
def process_font(self):
        for input_node, def_name in self.font_nodes:
                output_node = input_node.change_ext('.ttf.' + str(def_name) + '.pfo')
                self.pack_entries.append((output_node, def_name))
                if not getattr(self, 'dry_run', False):
                        font_tsk = self.create_task('genpfo', [input_node], [output_node])
                        font_tsk.resources = self.resources
                        font_tsk.fontscript = self.fontscript
                        font_tsk.fontheight = str(self.fonts[def_name]['height'])
                        font_tsk.trackarg = self.fonts[def_name]['tracking']
                        font_tsk.regex = self.fonts[def_name]['regex']

class genpfo(resources):
	color = 'BLUE'
        def run(self):
                return self.exec_command("{} '{}' pfo {} {} {} '{}' '{}'".format(
                        self.env.PYTHON[0], self.fontscript, self.fontheight, self.trackarg,
                        self.regex, self.inputs[0].abspath(), self.outputs[0].abspath()))

@feature('appinfo_res')
@after_method('process_trans_pbi')
def process_raw(self):
        for input_node, def_name in self.raw_nodes:
                self.pack_entries.append((input_node, def_name))

@feature('datapack')
def init_datapack(self):
        y = self.bld.get_tgen_by_name(getattr(self, 'use', []))
        y.post()
        self.pack_entries = y.pack_entries
        self.entry_nodes = [e[0] for e in self.pack_entries]
        self.entry_names = [e[1] for e in self.pack_entries]

        self.output_pack_node = self.path.find_or_declare('app_resources.pbpack')

	sdk_folder = self.bld.root.find_dir(self.bld.env['PEBBLE_SDK'])
        tools_path = sdk_folder.find_dir('tools')
        self.mdscript = tools_path.find_node('pbpack_meta_data.py').abspath()
        self.headerscript = tools_path.find_node('generate_resource_code.py').abspath()

	self.timestamp = self.bld.options.timestamp
	if self.timestamp == None:
		self.timestamp=int(time.time())

        self.packs = []

@feature('datapack')
@after_method('init_datapack')
def process_packdata(self):
        self.data_node = self.output_pack_node.change_ext('.pbpack.data')
        self.packs.append(self.data_node)
        pbdata_tsk = self.create_task('genpackdata' if self.entry_nodes else 'touch',
                                      self.entry_nodes, [self.data_node])

class touch(Task.Task):
        color = 'BLUE'
        def run(self): open(self.outputs[0].abspath(), 'a').close()

class genpackdata(Task.Task):
        color = 'BLUE'
        def run(self):
                cat_string="cat"
                for entry in self.inputs:
                        cat_string += ' "{}" '.format(entry.abspath())
                cat_string += ' > "{}" '.format(self.outputs[0].abspath())
                return self.exec_command(cat_string)

@feature('datapack')
@after_method('process_packdata')
def process_packtable(self):
        table_node = self.output_pack_node.change_ext('.pbpack.table')
        self.packs.append(table_node)
	pbtable_tsk = self.create_task('genpacktable', self.entry_nodes, [table_node])
        pbtable_tsk.mdscript = self.mdscript

class genpacktable(Task.Task):
        color = 'BLUE'

        def run(self):
                table_string="{} {} table {}".format(self.env.PYTHON[0],
                                                     self.mdscript,
                                                     self.outputs[0].abspath())
                for entry in self.inputs:
                        table_string += ' {} '.format(entry.abspath())
                return self.exec_command(table_string)

@feature('datapack')
@after_method('process_packtable')
def process_packmanifest(self):
        manifest_node = self.output_pack_node.change_ext('.pbpack.manifest')
        self.packs.append(manifest_node)
        manifest_tsk = self.create_task('genmanifest', [self.data_node], [manifest_node])
        manifest_tsk.env.append_value('MDSCRIPT', [self.mdscript])
        manifest_tsk.env.append_value('NUMFILES', [str(len(self.entry_nodes))])
        manifest_tsk.env.append_value('TIMESTAMP', [str(self.timestamp)])

class genmanifest(Task.Task):
        color = 'BLUE'
        run_str = '${PYTHON} ${MDSCRIPT} manifest ${TGT} ${NUMFILES} ${TIMESTAMP} ${SRC}'

@feature('datapack')
@after_method('process_packmanifest')
def process_pbpack(self):
        pbpack_tsk = self.create_task('genpbpack', self.packs, [self.output_pack_node])

class genpbpack(Task.Task):
        color = 'BLUE'
        def run(self):
                pbpack_string = 'cat {} {} {} > {}'.format(self.inputs[0].abspath(),
                                                           self.inputs[1].abspath(),
                                                           self.inputs[2].abspath(),
                                                           self.outputs[0].abspath())
                return self.exec_command(pbpack_string)

@feature('datapack')
@after_method('process_pbpack')
def process_appinfo_h(self):
        resource_id_header_node = self.path.find_or_declare('src/resource_ids.auto.h')

	header_tsk = self.create_task('genheader',
                                      [self.data_node] + self.entry_nodes,
                                      [resource_id_header_node])
        header_tsk.script = self.headerscript
        header_tsk.timestamp = self.timestamp
        header_tsk.resource_header_path = getattr(self, 'header_path', '')
        header_tsk.def_names = self.entry_names

class genheader(Task.Task):
        color = 'YELLOW'
        ext_out = ['.h']

        def run(self):
                header_string = '{} {} resource_header {} {} {} {}'.format(self.env.PYTHON[0],
                                                                           self.script,
                                                                           self.outputs[0].abspath(),
                                                                           self.timestamp,
                                                                           self.resource_header_path,
                                                                           self.inputs[0])
                for entry, name in zip(self.inputs[1:], self.def_names):
                        header_string += ' "%s" '%str(entry.abspath())+' "%s" '%str(name)
                return self.exec_command(header_string)

@feature('appinfo_auto_c')
@before_method('process_source')
def process_appinfo_c(self):
        appinfo_json_node = getattr(self, 'appinfo', None)
        self.appinfo_c_node = appinfo_json_node.change_ext('.auto.c')
        genautoc_tsk = self.create_task('appinfo_c', [appinfo_json_node], [self.appinfo_c_node])

class appinfo_c(Task.Task):
	color   = 'GREEN'
        def run(self):
                import waflib.extras.generate_appinfo as generate_appinfo
                generate_appinfo.generate_appinfo(self.inputs[0].abspath(),
                                                  self.outputs[0].abspath())

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

@feature('cprogram_pebble')
@before_method('process_source')
def setup_pebble_cprogram(self):
	sdk_folder=self.bld.root.find_dir(self.bld.env['PEBBLE_SDK'])
	append_to_attr(self,'source',[self.path.find_or_declare('appinfo.auto.c')])
	append_to_attr(self,'stlibpath',[sdk_folder.find_dir('lib').abspath()])
	append_to_attr(self,'stlib',['pebble'])
	append_to_attr(self,'linkflags',['-Wl,-Map,pebble-app.map,--emit-relocs'])
        if not getattr(self, 'ldscript', False):
                setattr(self,'ldscript',sdk_folder.find_node('pebble_app.ld').path_from(self.bld.path))

@feature('pbl_bundle')
def init_pbl_bundle(self):
        self.timestamp = self.bld.options.timestamp
	if self.timestamp is None:
		self.timestamp = int(time.time())

        self.pbw_basename = 'app_'+str(self.timestamp) if self.timestamp else self.bld.path.name

	self.elf_file_node = self.bld.path.find_or_declare(getattr(self,'elf'))
	if self.elf_file_node is None:
		raise Exception("Must specify elf argument to pbl_bundle")

        self.raw_bin_file_node = self.path.find_or_declare('pebble-app.raw.bin')

@feature('pbl_bundle')
@after_method('init_pbl_bundle')
def make_raw_bin_file(self):
        genraw_tsk = self.create_task('genrawbin', [self.elf_file_node], [self.raw_bin_file_node])

class genrawbin(Task.Task):
        color = 'YELLOW'
        run_str = "${OBJCPY} -S -R .stack -R .priv_bss -R .bss -O binary ${SRC} ${TGT}"

@feature('pbl_bundle')
@after_method('make_raw_bin_file')
def inject_medatada(self):
	self.js_nodes = self.to_nodes(getattr(self,'js',[]))
	has_jsapp = len(self.js_nodes) > 0

	resources_file_node = self.path.find_or_declare('app_resources.pbpack.data')
	self.bin_file_node = self.path.find_or_declare('pebble-app.bin')

        meta_tsk = self.create_task('injectdata',
                                    [self.raw_bin_file_node,
                                     self.elf_file_node,
                                     resources_file_node],
                                    [self.bin_file_node])

        meta_tsk.timestamp = self.timestamp
        meta_tsk.allow_js = has_jsapp

class injectdata(Task.Task):
        color = 'YELLOW'

        def run(self):
		cp_result = self.exec_command('cp "{}" "{}"'.format(self.inputs[0].abspath(),
                                                                    self.outputs[0].abspath()))
		if cp_result < 0:
			from waflib.Errors import BuildError
			raise BuildError("Failed to copy {} to {}!".format(bin_path,tgt_path))

                inject_metadata.inject_metadata(self.outputs[0].abspath(),
                                                self.inputs[1].abspath(),
                                                self.inputs[2].abspath(),
                                                self.timestamp,
                                                allow_js = self.allow_js)

@feature('pbl_bundle')
@after_method('inject_medatadata')
def create_watchapp_bundle(self):
	resources_pack_node = self.path.find_or_declare('app_resources.pbpack')
	pbz_output_node = self.bld.path.find_or_declare(self.pbw_basename + '.pbw')
        json_node = self.bld.path.find_node('appinfo.json')

        watchapp_tsk = self.create_task('watchapp',
                                        [self.bin_file_node, resources_pack_node, json_node] + self.js_nodes,
                                        [pbz_output_node])
        watchapp_tsk.timestamp = self.timestamp

class watchapp(Task.Task):
        color = 'BLUE'

        def run(self):
		return mkbundle.make_watchapp_bundle(
                        appinfo = self.inputs[2].abspath(),
                        js_files = [n.abspath() for n in self.inputs[3:]],
                        watchapp = self.inputs[0].abspath(),
                        watchapp_timestamp = self.timestamp,
                        sdk_version = SDK_VERSION,
                        resources = self.inputs[1].abspath(),
                        resources_timestamp = self.timestamp,
                        outfile = self.outputs[0].abspath())

@feature('pbl_bundle')
@after_method('create_watchapp_bundle')
def measure_memory_usage(self):
        self.create_task('reportmemory', [self.elf_file_node], [])

class reportmemory(Task.Task):
        color = 'YELLOW'

        def run(self):
		src_path = self.inputs[0].abspath()
		size_output = self.generator.bld.cmd_and_log([self.env.SIZE,src_path],
                                                             quiet = waflib.Context.BOTH,
                                                             output = waflib.Context.STDOUT)
		text_size, data_size, bss_size = \
                [int(x)for x in size_output.splitlines()[1].split()[:3]]
		app_ram_size = data_size + bss_size + text_size
		max_app_ram = inject_metadata.MAX_APP_MEMORY_SIZE
		free_size = max_app_ram-app_ram_size
		Logs.pprint('BLUE',"Memory usage:\n=============\n""Total app footprint in RAM:     %6u bytes / ~%ukb\n""Free RAM available (heap):      %6u bytes\n"%(app_ram_size,max_app_ram/1024,free_size))

from waflib.Configure import conf
@conf
def pbl_bundle(self,*k,**kw):
	kw['features']='pbl_bundle'
	return self(*k,**kw)
@conf
def pbl_program(self,*k,**kw):
	kw['features']='c cprogram cprogram_pebble'
	return self(*k,**kw)
