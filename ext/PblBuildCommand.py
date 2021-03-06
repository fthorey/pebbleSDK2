
import logging
import sh, os, subprocess
import json
import StringIO
import traceback
import sys

import PblAnalytics
from PblCommand import PblCommand
from PblProjectCreator import requires_project_dir
from LibPebblesCommand import (NoCompilerException, BuildErrorException,
                               AppTooBigException)



########################################################################
def create_sh_cmd_obj(cmdPath):
    """ Create a sh.Command() instance and check for error condition of
    the executable not in the path.

    If the argument to sh.Command can not be found in the path, then
    executing it raises a very obscure exception:
        'TypeError: sequence item 0: expected string, NoneType found'

    This method raise a more description exception.

    NOTE: If you use the sh.<cmdname>(cmdargs) syntax for calling
    a command instead of sh.Command(<cmdname>), the sh module returns a
    more descriptive sh.CommandNotFound exception. But, if the cmdname
    includes a directory path in it, you must use this sh.Command()
    syntax.
    """

    cmdObj = sh.Command(cmdPath)

    # By checking the _path member of the cmdObj, we can do a pre-flight to
    # detect this situation and raise a more friendly error message
    if cmdObj._path is None:
        raise RuntimeError("The executable %s could not be "
                           "found. " % (cmdPath))

    return cmdObj


###############################################################################
###############################################################################
class PblWafCommand(PblCommand):
    """ Helper class for build commands that execute waf """

    waf_cmds = ""

    ###########################################################################
    def waf_path(self, args):
        path = os.path.join(self.sdk_path(args), 'Pebble', 'waf')
        if not os.path.exists(path):
            raise Exception("Unable to locate waf at '{}'".format(path))
        return path


    ###########################################################################
    def _send_memory_usage(self, args, appInfo):
        """ Send app memory usage to analytics

        Parameters:
        --------------------------------------------------------------------
        args: the args passed to the run() method
        appInfo: the applications appInfo
        """

        cmdName = 'arm_none_eabi_size'
        cmdArgs = [os.path.join("build", "pebble-app.elf")]
        try:
            output = sh.arm_none_eabi_size(*cmdArgs, _tty_out=False)
            (textSize, dataSize, bssSize) = [int(x) for x in \
                                     output.stdout.splitlines()[1].split()[:3]]
            sizeDict = {'text': textSize, 'data': dataSize, 'bss': bssSize}
            PblAnalytics.code_size_evt(uuid=appInfo["uuid"],
                                    segSizes = sizeDict)
        except sh.ErrorReturnCode as e:
            logging.error("command %s %s failed. stdout: %s, stderr: %s" %
                          (cmdName, ' '.join(cmdArgs), e.stdout, e.stderr))
        except sh.CommandNotFound as e:
            logging.error("The command %s could not be found. Could not "
                          "collect memory usage analytics." % (e.message))


    ###########################################################################
    def _count_lines(self, path, exts):
        """ Count number of lines of source code in the given path. This will
        recurse into subdirectories as well.

        Parameters:
        --------------------------------------------------------------------
        path: directory name to search
        exts: list of extensions to include in the search, i.e. ['.c', '.h']
        """

        srcLines = 0
        files = os.listdir(path)
        for name in files:
            if name.startswith('.'):
                continue
            if os.path.isdir(os.path.join(path, name)):
                if not os.path.islink(os.path.join(path, name)):
                    srcLines += self._count_lines(os.path.join(path, name), exts)
                continue
            ext = os.path.splitext(name)[1]
            if ext in exts:
                srcLines += sum(1 for line in open(os.path.join(path, name)))
        return srcLines


    ###########################################################################
    def _send_line_counts(self, args, appInfo):
        """ Send app line counts up to analytics

        Parameters:
        --------------------------------------------------------------------
        args: the args passed to the run() method
        appInfo: the applications appInfo
        """

        c_line_count = 0
        js_line_count = 0
        if os.path.exists('src'):
            c_line_count += self._count_lines('src', ['.h', '.c'])
            js_line_count += self._count_lines('src', ['.js'])

        PblAnalytics.code_line_count_evt(uuid=appInfo["uuid"],
                                c_line_count = c_line_count,
                                js_line_count = js_line_count)


    ###########################################################################
    def _send_resource_usage(self, args, appInfo):
        """ Send app resource usage up to analytics

        Parameters:
        --------------------------------------------------------------------
        args: the args passed to the run() method
        appInfo: the applications appInfo
        """

        # Collect the number and total size of each class of resource:
        resCounts = {"raw": 0, "image": 0, "font": 0}
        resSizes = {"raw": 0, "image": 0, "font": 0}

        for resDict in appInfo["resources"]["media"]:
            if resDict["type"] in ["png", "png-trans"]:
                type = "image"
            elif resDict["type"] in ["font"]:
                type = "font"
            elif resDict["type"] in ["raw"]:
                type = "raw"
            else:
                raise RuntimeError("Unsupported resource type %s" %
                                (resDict["type"]))

            # Look for the generated blob in the build/resource directory.
            # As far as we can tell, the generated blob always starts with
            # the original filename and adds an extension to it, or (for
            # fonts), a name and extension.
            (dirName, fileName) = os.path.split(resDict["file"])
            dirToSearch = [os.path.join("build", "resources", dirName)]
            if type == "raw":
                           dirToSearch.append(os.path.join("resources", dirName))
            found = False
            for dir in dirToSearch:
                for name in os.listdir(dir):
                    if (type == "raw" and name == fileName) \
                       or (type != 'raw' and name.startswith(fileName)
                           and name != fileName):
                        size = os.path.getsize(os.path.join(dir, name))
                        found = True
                        break
            if not found:
                raise RuntimeError("Could not find generated resource "
                                   "corresponding to %s." % (resDict["file"]))

            resCounts[type] += 1
            resSizes[type] += size

        # Send the stats now
        PblAnalytics.res_sizes_evt(uuid=appInfo["uuid"],
                                 resCounts = resCounts,
                                 resSizes = resSizes)


    ###########################################################################
    @requires_project_dir
    def run(self, args):
        os.environ['PATH'] = "{}:{}".format(
            os.path.join(self.sdk_path(args), "arm-cs-tools", "bin"),
            os.environ['PATH'])

        # If python3 is the default and python2 is available, then plug in
        #  our stub 'python' shell script which passes control to python2
        py_version = sh.python("-c",
                               "import sys;print(sys.version_info[0])",
                               _tty_out=False).strip()
        if py_version != '2':
            if sh.which('python2', _tty_out=False) is None:
                raise RuntimeError("The Pebble SDK requires python version 2.6 "
                    "or 2.7 (python2). You are currently running 'python%s' "
                    "by default and a 'python2' executable could not be found." %
                    py_version)
            os.environ['PATH'] = "{}:{}".format(
                os.path.join(os.path.normpath(os.path.dirname(__file__))),
                os.environ['PATH'])

        # Execute the build command
        cmdLine = '"%s" %s' % (self.waf_path(args), self.waf_cmds)
        retval = subprocess.call(cmdLine, shell=True)

        # If an error occurred, we need to do some sleuthing to determine a
        # cause. This allows the caller to post more useful information to
        # analytics. We normally don't capture stdout and stderr using Poepn()
        # because you lose the nice color coding produced when the command
        # outputs to a terminal directly.
        #
        # But, if an error occurs, let's run it again capturing the output
        #  so we can determine the cause
        if (retval):
            cmdArgs = [self.waf_path(args)] + self.waf_cmds.split()
            try:
                cmdObj = create_sh_cmd_obj(cmdArgs[0])
                output = cmdObj(*cmdArgs[1:])
                stderr = output.stderr
            except sh.ErrorReturnCode as e:
                stderr = e.stderr

            # Look for common problems
            if "Could not determine the compiler version" in stderr:
                raise NoCompilerException

            elif "region `APP' overflowed" in stderr:
                raise AppTooBigException

            else:
                raise BuildErrorException

        elif args.command == 'build':
            # No error building. Send up app memory usage and resource usage
            #  up to analytics
            # Read in the appinfo.json to get the list of resources
            try:
                appInfo = json.load(open("appinfo.json"))
                self._send_memory_usage(args, appInfo)
                self._send_resource_usage(args, appInfo)
                self._send_line_counts(args, appInfo)
                hasJS = os.path.exists(os.path.join('src', 'js'))
                PblAnalytics.code_has_java_script_evt(uuid=appInfo["uuid"],
                                         hasJS=hasJS)
            except Exception as e:
                logging.error("Exception occurred collecting app analytics: "
                              "%s" % str(e))
                logging.debug(traceback.format_exc())

        return 0

    ###########################################################################
    def configure_subparser(self, parser):
        PblCommand.configure_subparser(self, parser)


###########################################################################
###########################################################################
class PblBuildCommand(PblWafCommand):
    name = 'build'
    help = 'Build your Pebble project'
    waf_cmds = 'configure build -v'

###########################################################################
###########################################################################
class PblCleanCommand(PblWafCommand):
    name = 'clean'
    help = 'Clean your Pebble project'
    waf_cmds = 'distclean'


class PblAnalyzeSizeCommand(PblCommand):
    name = 'analyze-size'
    help = 'Analyze the size of your Pebble app'

    def configure_subparser(self, parser):
        PblCommand.configure_subparser(self, parser)
        parser.add_argument('elf_path', type=str, nargs='?', default='build/pebble-app.elf',
                help='Path to the elf file to analyze')
        parser.add_argument('--summary', action='store_true', help='Display a single line per section')
        parser.add_argument('--verbose', action='store_true', help='Display a per-symbol breakdown')

    @requires_project_dir
    def run(self, args):
        sys.path.append(os.path.join(self.sdk_path(args), 'Pebble', 'tools'))
        import analyze_static_memory_usage

        sections = analyze_static_memory_usage.make_sections_dict('bdt')

        analyze_static_memory_usage.analyze_elf(args.elf_path, sections)

        for s in sections.itervalues():
            s.pprint(args.summary, args.verbose)
