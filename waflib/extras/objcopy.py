#! /usr/bin/env python
# encoding: utf-8
# WARNING! Do not edit! http://waf.googlecode.com/git/docs/wafbook/single.html#_obtaining_the_waf_file

def objcopy(task,mode):
	return task.exec_command('arm-none-eabi-objcopy -S -R .stack -R .priv_bss'' -R .bss -O %s "%s" "%s"'%(mode,task.inputs[0].abspath(),task.outputs[0].abspath()))
def objcopy_fill_bss(task,mode):
	return task.exec_command('arm-none-eabi-objcopy -O %s -j .text -j .data ''-j .bss --set-section-flags .bss=alloc,load,contents "%s" "%s"'%(mode,task.inputs[0].abspath(),task.outputs[0].abspath()))
def objcopy_hex(task):
	return objcopy(task,'ihex')
def objcopy_bin(task):
	return objcopy(task,'binary')
