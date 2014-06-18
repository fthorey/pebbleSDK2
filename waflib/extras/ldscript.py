#! /usr/bin/env python
# encoding: utf-8
# WARNING! Do not edit! http://waf.googlecode.com/git/docs/wafbook/single.html#_obtaining_the_waf_file

from waflib import Utils,Errors
from waflib.TaskGen import after,feature
@after('apply_link')
@feature('cprogram','cshlib')
def process_ldscript(self):
	if not getattr(self,'ldscript',None)or self.env.CC_NAME!='gcc':
		return
	node=self.path.find_resource(self.ldscript)
	if not node:
		raise Errors.WafError('could not find %r'%self.ldscript)
	self.link_task.env.append_value('LINKFLAGS','-T%s'%node.abspath())
	self.link_task.dep_nodes.append(node)
