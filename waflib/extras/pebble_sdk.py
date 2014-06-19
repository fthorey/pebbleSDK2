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

	opt.add_option('-t','--timestamp',dest='timestamp', default = 0,
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
        if arm_path is not []:
                os.environ['PATH'] = os.pathsep.join(arm_path) + os.pathsep + os.environ['PATH']

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

def build(bld):
        c_preproc.enable_file_name_c_define()

        appinfo_json_node = bld.path.find_node('appinfo.json')
	if appinfo_json_node is None:
		bld.fatal('Could not find appinfo.json')
        with open(appinfo_json_node.abspath(), 'r') as f:
                appinfo = json.load(f)
        resources = appinfo['resources']

        bld(features       = 'appinfo_res',
            name           = 'gen_appinfo_res',
            resources      = resources,
        )

	sdk_folder = bld.root.find_dir(bld.env['PEBBLE_SDK'])
        tools_path = sdk_folder.find_dir('tools')

        output_pack_node = bld.path.find_or_declare('app_resources.pbpack')
        manifest_node = output_pack_node.change_ext('.pbpack.manifest')
        table_node = output_pack_node.change_ext('.pbpack.table')
        data_node = output_pack_node.change_ext('.pbpack.data')

        bld(features      = 'packdata',
            name          = 'gen_packdata',
            target        = data_node,
            resource_dep  = ['gen_appinfo_res'])

        bld(features       = 'packtable',
            name           = 'gen_packtable',
            target         = table_node,
            script         = tools_path.find_node('pbpack_meta_data.py').abspath(),
            resource_dep   = ['gen_appinfo_res'])

        bld(features       = 'packmanifest',
            name           = 'gen_packmanifest',
            data           = data_node,
            target         = manifest_node,
            script         = tools_path.find_node('pbpack_meta_data.py').abspath(),
            resource_dep   = ['gen_appinfo_res'])

        bld(features       = 'pbpack',
            name           = 'gen_pbpack',
            packs          = [manifest_node, table_node, data_node],
            target         = output_pack_node)

        # resource_id_header_node = bld.path.find_or_declare('src/resource_ids.auto.h')

        # bld(features       = 'ids_auto_h',
        #     name           = 'gen_ids_auto_h',
        #     data           = data_node,
        #     target         = resource_id_header_node,
        #     script         = tools_path.find_node('generate_resource_code.py').abspath(),
        #     header_path    = 'pebble.h',
        #     resource_dep   = ['png_proc', 'png-trans_proc', 'font_proc', 'raw_proc'])

        # appinfo_auto_c_node = appinfo_json_node.change_ext('.auto.c')

        # bld(features       = 'appinfo_auto_c',
        #     name           = 'gen_appinfo_auto_c',
        #     appinfo        = appinfo_json_node,
        #     target         = appinfo_auto_c_node)

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

def process(tg):
        lst_raw, lst_png, lst_png_trans, lst_font = [], [], [], []
        resources_node = tg.bld.srcnode.find_node('resources')
        for res in tg.resources['media']:
                def_name = res["name"]
                res_type=res["type"]
                input_file=str(res["file"])
                input_node = resources_node.find_node(input_file)
                if input_node is None:
                        tg.fatal("Could not find {} resource <{}>"
                                 .format(res_type,input_file))
                else:
                        if res_type == 'raw':
                                lst_raw.append((input_node, def_name))
                        elif res_type == 'png':
                                lst_png.append((input_node, def_name))
                        elif res_type == 'png-trans':
                                lst_png_trans.append((input_node, def_name))
                        elif res_type == 'font':
                                lst_font.append((input_node, def_name))
        return lst_raw, lst_png, lst_png_trans, lst_font

@feature('appinfo_res')
def init_appinfo_res(self):
        self.pack_entries = []
        self.resources = getattr(self, 'resources', False)

	sdk_folder = self.bld.root.find_dir(self.bld.env['PEBBLE_SDK'])
        tools_path = sdk_folder.find_dir('tools')

        self.bitmapscript = tools_path.find_node('bitmapgen.py').abspath()
        self.fontscript = tools_path.find_node('font/fontgen.py').abspath()

        self.raw_nodes, self.png_nodes, self.png_trans_nodes, self.font_nodes = process(self)

@feature('appinfo_res')
@after_method('init_appinfo_res')
def process_bpi(self):
        for input_node, def_name in self.png_nodes:
                output_node = input_node.change_ext('.png.pbi')
                self.pack_entries.append((output_node, def_name))
                pbi_tsk = self.create_task('genpbi',
                                           [input_node],
                                           [output_node])
                pbi_tsk.resources = self.resources
                pbi_tsk.env.append_value('BITMAPSCRIPT', [self.bitmapscript])

@feature('appinfo_res')
@after_method('process_pbi')
def process_trans_bpi(self):
        for input_node, def_name in self.png_trans_nodes:
                for color in ['white', 'black']:
                        output_node = input_node.change_ext(".png.{}.pbi".format(color))
                        self.pack_entries.append((output_node,"{}_{}".format(def_name, color.upper())))
                        pbi_tsk = self.create_task('genpbi',
                                                   [input_node],
                                                   [output_node])
                        pbi_tsk.resources = self.resources
                        pbi_tsk.env.append_value('BITMAPSCRIPT', [self.bitmapscript])

class genpbi(resources):
        color = 'BLUE'
        run_str = '${PYTHON} ${BITMAPSCRIPT} pbi ${SRC} ${TGT}'

@feature('appinfo_res')
@after_method('process_trans_pbi')
def process_font(self):
        for input_node, def_name in self.font_nodes:
                output_node = input_node.change_ext('.' + str(def_name) + '.pfo')
                self.pack_entries.append((output_node, def_name))
                font_tsk = self.create_task('genpfo',
                                            [input_node],
                                            [output_node])
                m = re.search('([0-9]+)', def_name)
                if m == None:
                        if def_name != 'FONT_FALLBACK':
                                raise ValueError('Font {0}: no height found in def name''\n'
                                                 .format(self.def_name))
                                height = 14
                else:
                        height = int(m.group(0))

                font_tsk.resources = self.resources
                font_tsk.env.append_value('FONTSCRIPT', [self.fontscript])
                font_tsk.env.append_value('FONTHEIGHT', [str(height)])

class genpfo(resources):
        color = 'BLUE'
        run_str = '${PYTHON} ${FONTSCRIPT} pfo ${FONTHEIGHT} ${SRC} ${TGT}'

@feature('appinfo_res')
@after_method('process_font')
def process_raw(self):
        for input_node, def_name in self.raw_nodes:
                self.pack_entries.append((input_node, def_name))

@feature('packdata')
def process_packdata(self):
        target = getattr(self, 'target', False)

        entries = []

        for x in self.to_list(getattr(self, 'resource_dep', [])):
                y = self.bld.get_tgen_by_name(x)
                y.post()
                if getattr(y, 'pack_entries', None):
                        entries += y.pack_entries

        pbdata_tsk = self.create_task('genpackdata' if entries else 'touch', [e[0] for e in entries], [target])

class touch(Task.Task):
        color = 'BLUE'

        def run(self):
		open(self.outputs[0].abspath(), 'a').close()


class genpackdata(Task.Task):
        color = 'BLUE'

        def run(self):
                cat_string="cat"
                for entry in self.inputs:
                        cat_string += ' "{}" '.format(entry.abspath())
                cat_string += ' > "{}" '.format(self.outputs[0].abspath())
                return self.exec_command(cat_string)

@feature('packtable')
def process_packtable(self):
        target = getattr(self, 'target', False)

        entries = []

        for x in self.to_list(getattr(self, 'resource_dep', [])):
                y = self.bld.get_tgen_by_name(x)
                y.post()
                if getattr(y, 'pack_entries', None):
                        entries += y.pack_entries

	pbtable_tsk = self.create_task('genpacktable', [e[0] for e in entries], [target])
        pbtable_tsk.mdscript = getattr(self, 'script', False)

class genpacktable(Task.Task):
        color = 'BLUE'

        def run(self):
                table_string="{} {} table {}".format(self.env.PYTHON[0],
                                                     self.mdscript,
                                                     self.outputs[0].abspath())
                for entry in self.inputs:
                        table_string += ' {} '.format(entry.abspath())
                return self.exec_command(table_string)

@feature('packmanifest')
def process_packmanifest(self):
        target = getattr(self, 'target', False)
        script = getattr(self, 'script', False)
        data = getattr(self, 'data', False)

        entries = []
        for x in self.to_list(getattr(self, 'resource_dep', [])):
                y = self.bld.get_tgen_by_name(x)
                y.post()
                if getattr(y, 'pack_entries', None):
                        entries += y.pack_entries

        # timestamp = int(time.time())
        timestamp = str(0)

        manifest_tsk = self.create_task('genmanifest', [data], [target])
        manifest_tsk.env.append_value('MDSCRIPT', [script])
        manifest_tsk.env.append_value('NUMFILES', [str(len(entries))])
        manifest_tsk.env.append_value('TIMESTAMP', [str(timestamp)])

class genmanifest(Task.Task):
        color = 'BLUE'
        run_str = '${PYTHON} ${MDSCRIPT} manifest ${TGT} ${NUMFILES} ${TIMESTAMP} ${SRC}'

@feature('pbpack')
def process_pbpack(self):
        target = getattr(self, 'target', False)
        packs = getattr(self, 'packs', False)
        pbpack_tsk = self.create_task('genpbpack', packs, [target])

class genpbpack(Task.Task):
        color = 'BLUE'
        def run(self):
                pbpack_string = 'cat {} {} {} > {}'.format(self.inputs[0], self.inputs[1],
                                                           self.inputs[2], self.outputs[0])
                return self.exec_command(pbpack_string)

@feature('ids_auto_h')
def process_appinfo_h(self):
        target = getattr(self, 'target', False)
        data = getattr(self, 'data', False)

        entries = []

        for x in self.to_list(getattr(self, 'resource_dep', [])):
                y = self.bld.get_tgen_by_name(x)
                y.post()
                if getattr(y, 'pack_entries', None):
                        entries += y.pack_entries

	header_tsk = self.create_task('genheader', [data] + [e[0] for e in entries], [target])
        header_tsk.script = getattr(self, 'script', False)
        # header_tsk.timestamp = str(int(time.time()))
        header_tsk.timestamp = str(0)
        header_tsk.resource_header_path = getattr(self, 'header_path', '')
        header_tsk.def_names = [e[1] for e in entries]

class genheader(Task.Task):
        color = 'BLUE'
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
        appinfo = getattr(self, 'appinfo', None)
        self.target = getattr(self, 'target', None)

        genautoc_tsk = self.create_task('genautoc', [appinfo], [self.target])

class genautoc(Task.Task):
	color   = 'GREEN'

        def run(self):
                import waflib.extras.generate_appinfo as generate_appinfo
                generate_appinfo.generate_appinfo(self.inputs[0].abspath(),
                                                  self.outputs[0].abspath())

@feature('c')
@before_method('process_source')
def retrieve_appinfo_c(self):

        for x in self.to_list('gen_appinfo_auto_c'):
                y = self.bld.get_tgen_by_name(x)
                y.post()
                if getattr(y, 'target', None):
                        self.source.append(y.target)

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
	append_to_attr(self,'stlibpath',[sdk_folder.find_dir('lib').abspath()])
	append_to_attr(self,'stlib',['pebble'])
	append_to_attr(self,'linkflags',['-Wl,-Map,pebble-app.map,--emit-relocs'])
        if not getattr(self, 'ldscript', False):
                setattr(self,'ldscript',sdk_folder.find_node('pebble_app.ld').path_from(self.bld.path))

@feature('pbl_bundle')
def make_pbl_bundle(self):
	timestamp=self.bld.options.timestamp
	pbw_basename='app_'+str(timestamp) if timestamp else self.bld.path.name

	if timestamp is None:
		timestamp=int(time.time())

	elf_file_node = self.bld.path.find_or_declare(getattr(self,'elf'))
	if elf_file_node is None:
		raise Exception("Must specify elf argument to pbl_bundle")

	raw_bin_file_node = self.path.find_or_declare('pebble-app.raw.bin')

	self.bld(rule = objcopy.objcopy_bin, source = elf_file_node, target = raw_bin_file_node)

	js_nodes = self.to_nodes(getattr(self,'js',[]))
	js_files=[x.abspath() for x in js_nodes]
	has_jsapp = len(js_nodes) > 0

	def inject_data_rule(task):
		bin_path=task.inputs[0].abspath()
		elf_path=task.inputs[1].abspath()
		res_path=task.inputs[2].abspath()
		tgt_path=task.outputs[0].abspath()
		cp_result=task.exec_command('cp "{}" "{}"'.format(bin_path,tgt_path))
		if cp_result<0:
			from waflib.Errors import BuildError
			raise BuildError("Failed to copy %s to %s!"%(bin_path,tgt_path))
		inject_metadata.inject_metadata(tgt_path,elf_path,res_path,timestamp,allow_js=has_jsapp)

	resources_file_node = self.path.find_or_declare('app_resources.pbpack.data')
	bin_file_node = self.path.find_or_declare('pebble-app.bin')

	self.bld(rule = inject_data_rule,name='inject-metadata',
                 source = [raw_bin_file_node , elf_file_node, resources_file_node],
                 target = bin_file_node)

	resources_pack_node = self.path.find_or_declare('app_resources.pbpack')
	pbz_output_node = self.bld.path.find_or_declare(pbw_basename + '.pbw')

	def make_watchapp_bundle(task):
		watchapp=task.inputs[0].abspath()
		resources=task.inputs[1].abspath()
		outfile=task.outputs[0].abspath()
		return mkbundle.make_watchapp_bundle(
                        appinfo = self.bld.path.get_src().find_node('appinfo.json').abspath(),
                        js_files = js_files,
                        watchapp = watchapp,
                        watchapp_timestamp = timestamp,
                        sdk_version = SDK_VERSION,
                        resources = resources,
                        resources_timestamp = timestamp,
                        outfile = outfile)

        self.bld(rule = make_watchapp_bundle,
                 source= [bin_file_node , resources_pack_node] + js_nodes,
                 target = pbz_output_node)

	def report_memory_usage(task):
		src_path = task.inputs[0].abspath()
		size_output = task.generator.bld.cmd_and_log([task.env.SIZE,src_path],
                                                             quiet = waflib.Context.BOTH,
                                                             output = waflib.Context.STDOUT)
		text_size, data_size, bss_size = [int(x)for x in size_output.splitlines()[1].split()[:3]]
		app_ram_size = data_size + bss_size + text_size
		max_app_ram = inject_metadata.MAX_APP_MEMORY_SIZE
		free_size = max_app_ram-app_ram_size
		Logs.pprint('YELLOW',"Memory usage:\n=============\n""Total app footprint in RAM:     %6u bytes / ~%ukb\n""Free RAM available (heap):      %6u bytes\n"%(app_ram_size,max_app_ram/1024,free_size))

	self.bld(rule = report_memory_usage,
                 name = 'report-memory-usage',
                 source = [elf_file_node],
                 target=None)

from waflib.Configure import conf
@conf
def pbl_bundle(self,*k,**kw):
	kw['features']='pbl_bundle'
	return self(*k,**kw)
@conf
def pbl_program(self,*k,**kw):
	kw['features']='c cprogram cprogram_pebble'
	return self(*k,**kw)
