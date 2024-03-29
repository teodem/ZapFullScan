#!/usr/bin/env python
# Zed Attack Proxy (ZAP) and its related class files.
#
# ZAP is an HTTP/HTTPS proxy for assessing web application security.
#
# Copyright 2016 ZAP Development Team
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# This file contains code from Dick Snel and Alwin Peppels from
# https://github.com/ICTU/zap-baseline.git and ported to a new
# ZAP version.
#
# This script runs a baseline scan against a target URL using ZAP
#
# It can either be run 'standalone', in which case depends on
# https://pypi.python.org/pypi/python-owasp-zap-v2.4 and Docker, or it can be run
# inside one of the ZAP docker containers. It automatically detects if it is
# running in docker so the parameters are the same.
#
# By default it will spider the target URL for one minute, but you can change
# that via the -m parameter.
# It will then wait for the passive scanning to finish - how long that takes
# depends on the number of pages found.
# It will exit with codes of:
#	0:	Success
#	1:	At least 1 FAIL
#	2:	At least one WARN and no FAILs
#	3:	Any other failure
# By default all alerts found by ZAP will be treated as WARNings.
# You can use the -c or -u parameters to specify a configuration file to override
# this.
# You can generate a template configuration file using the -g parameter. You will
# then need to change 'WARN' to 'FAIL', 'INFO' or 'IGNORE' for the rules you want
# to be handled differently.
# You can also add your own messages for the rules by appending them after a tab
# at the end of each line.

import getopt
import logging
import os
import os.path
import sys
import time
from datetime import datetime
from six.moves.urllib.request import urlopen
from zapv2 import ZAPv2
from zap_common import *

from selenium import webdriver
from pyvirtualdisplay import Display

config_dict = {}
config_msg = {}
out_of_scope_dict = {}
min_level = 0

# Pscan rules that aren't really relevant, eg the examples rules in the alpha set
blacklist = ['-1', '50003', '60000', '60001']

# Pscan rules that are being addressed
in_progress_issues = {}

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
# Hide "Starting new HTTP connection" messages
logging.getLogger("requests").setLevel(logging.WARNING)


def usage():
    print ('Usage: zap-baseline.py -t <target> [options]')
    print ('    -t target         target URL including the protocol, eg https://www.example.com')
    print ('Options:')
    print ('    -c config_file    config file to use to INFO, IGNORE or FAIL warnings')
    print ('    -u config_url     URL of config file to use to INFO, IGNORE or FAIL warnings')
    print ('    -g gen_file       generate default config file (all rules set to WARN)')
    print ('    -m mins           the number of minutes to spider for (default 1)')
    print ('    -r report_html    file to write the full ZAP HTML report')
    print ('    -w report_md      file to write the full ZAP Wiki (Markdown) report')
    print ('    -x report_xml     file to write the full ZAP XML report')
    print ('    -J report_json    file to write the full ZAP JSON document')
    print ('    -a                include the alpha passive scan rules as well')
    print ('    -d                show debug messages')
    print ('    -P                specify listen port')
    print ('    -D                delay in seconds to wait for passive scanning ')
    print ('    -i                default rules not in the config file to INFO')
    print ('    -j                use the Ajax spider in addition to the traditional one')
    print ('    -l level          minimum level to show: PASS, IGNORE, INFO, WARN or FAIL, use with -s to hide example URLs')
    print ('    -n context_file   context file which will be loaded prior to spidering the target')
    print ('    -p progress_file  progress file which specifies issues that are being addressed')
    print ('    -s                short output format - dont show PASSes or example URLs')
    print ('    -T                max time in minutes to wait for ZAP to start and the passive scan to run')
    print ('    -z zap_options    ZAP command line options e.g. -z "-config aaa=bbb -config ccc=ddd"')
    print ('Authentication:')
    print ('    --auth-url                 login form URL')
    print ('    --auth-username            username')
    print ('    --auth-password            password')
    print ('    --auth-username-field      name of username input field')
    print ('    --auth-password-field      name of password input field')
    print ('    --auth-submit-field        name or value of submit input')
    print ('    --auth-first-page          enable two-page authentication')
    print ('    --auth-first-submit-field  name or value of submit input of first page')
    print ('    --auth-exclude-urls        comma separated list of URLs to exclude, supply all URLs causing logout')
    print ('')
    print ('For more details see https://github.com/zaproxy/zaproxy/wiki/ZAP-Baseline-Scan')


def main(argv):
    global min_level
    global in_progress_issues
    cid = ''
    context_file = ''
    progress_file = ''
    config_file = ''
    config_url = ''
    generate = ''
    mins = 1
    port = 0
    detailed_output = True
    report_html = ''
    report_md = ''
    report_xml = ''
    report_json = ''
    target = ''
    zap_alpha = False
    info_unspecified = False
    ajax = False
    base_dir = ''
    zap_ip = 'localhost'
    zap_options = ''
    delay = 0
    timeout = 0
    auth_first_page = False
    auth_login_url = ''
    auth_username = ''
    auth_password = ''
    auth_username_field = 'email'
    auth_password_field = 'password'
    auth_submit_field = ''
    auth_first_submit_field = ''
    auth_exclude_urls = [];
    pass_count = 0
    warn_count = 0
    fail_count = 0
    info_count = 0
    ignore_count = 0
    warn_inprog_count = 0
    fail_inprog_count = 0

    check_zap_client_version()

    try:
        opts, args = getopt.getopt(argv, "t:c:u:g:m:n:r:J:w:x:l:daijp:sz:P:D:T:", ['auth-first-page', 'auth-url=', 'auth-username=', 'auth-password=', 'auth-username-field=', 'auth-password-field=', 'auth-first-submit-field=', 'auth-submit-field=', 'auth-exclude-urls='])
    except getopt.GetoptError as exc:
        logging.warning('Invalid option ' + exc.opt + ' : ' + exc.msg)
        usage()
        sys.exit(3)

    for opt, arg in opts:
        if opt == '-t':
            target = arg
            logging.debug('Target: ' + target)
        elif opt == '-c':
            config_file = arg
        elif opt == '-u':
            config_url = arg
        elif opt == '-g':
            generate = arg
        elif opt == '-d':
            logging.getLogger().setLevel(logging.DEBUG)
        elif opt == '-m':
            mins = int(arg)
        elif opt == '-P':
            port = int(arg)
        elif opt == '-D':
            delay = int(arg)
        elif opt == '-n':
            context_file = arg
        elif opt == '-p':
            progress_file = arg
        elif opt == '-r':
            report_html = arg
        elif opt == '-J':
            report_json = arg
        elif opt == '-w':
            report_md = arg
        elif opt == '-x':
            report_xml = arg
        elif opt == '-a':
            zap_alpha = True
        elif opt == '-i':
            info_unspecified = True
        elif opt == '-j':
            ajax = True
        elif opt == '--auth-first-page':
            auth_first_page = True
        elif opt == "--auth-username":
            auth_username = arg
        elif opt == "--auth-password":
            auth_password = arg
        elif opt == "--auth-url":
            auth_login_url = arg
        elif opt == "--auth-username-field":
            auth_username_field = arg
        elif opt == "--auth-password-field":
            auth_password_field = arg
        elif opt == "--auth-submit-field":
            auth_submit_field = arg
        elif opt == "--auth-first-submit-field":
            auth_first_submit_field = arg
        elif opt == "--auth-exclude-urls":
            auth_exclude_urls = arg.split(',')
        elif opt == '-l':
            try:
                min_level = zap_conf_lvls.index(arg)
            except ValueError:
                logging.warning('Level must be one of ' + str(zap_conf_lvls))
                usage()
                sys.exit(3)
        elif opt == '-z':
            zap_options = arg
        elif opt == '-s':
            detailed_output = False
        elif opt == '-T':
            timeout = int(arg)

    # Check target supplied and ok
    if len(target) == 0:
        usage()
        sys.exit(3)

    if not (target.startswith('http://') or target.startswith('https://')):
        logging.warning('Target must start with \'http://\' or \'https://\'')
        usage()
        sys.exit(3)

    if running_in_docker():
        base_dir = '/zap/wrk/'
        if config_file or generate or report_html or report_xml or report_json or progress_file or context_file:
            # Check directory has been mounted
            if not os.path.exists(base_dir):
                logging.warning('A file based option has been specified but the directory \'/zap/wrk\' is not mounted ')
                usage()
                sys.exit(3)

    # Choose a random 'ephemeral' port and check its available if it wasn't specified with -P option
    if port == 0:
        port = get_free_port()

    logging.debug('Using port: ' + str(port))

    if config_file:
        # load config file from filestore
        with open(base_dir + config_file) as f:
            try:
                load_config(f, config_dict, config_msg, out_of_scope_dict)
            except ValueError as e:
                logging.warning(e)
                sys.exit(3)
    elif config_url:
        # load config file from url
        try:
            load_config(urlopen(config_url).read().decode('UTF-8'), config_dict, config_msg, out_of_scope_dict)
        except ValueError as e:
            logging.warning(e)
            sys.exit(3)
        except:
            logging.warning('Failed to read configs from ' + config_url)
            sys.exit(3)

    if progress_file:
        # load progress file from filestore
        with open(base_dir + progress_file) as f:
            progress = json.load(f)
            # parse into something more useful...
            # in_prog_issues = map of vulnid -> {object with everything in}
            for issue in progress["issues"]:
                if issue["state"] == "inprogress":
                    in_progress_issues[issue["id"]] = issue

    if running_in_docker():
        try:
            params = [
                      '-config', 'spider.maxDuration=' + str(mins),
                      '-addonupdate',
                      '-addoninstall', 'pscanrulesBeta']  # In case we're running in the stable container

            if zap_alpha:
                params.append('-addoninstall')
                params.append('pscanrulesAlpha')

            if zap_options:
                for zap_opt in zap_options.split(" "):
                    params.append(zap_opt)

            start_zap(port, params)

        except OSError:
            logging.warning('Failed to start ZAP :(')
            sys.exit(3)

    else:
        # Not running in docker, so start one
        mount_dir = ''
        if context_file:
            mount_dir = os.path.dirname(os.path.abspath(context_file))

        params = [
                '-config', 'spider.maxDuration=' + str(mins),
                '-addonupdate']

        if (zap_alpha):
            params.extend(['-addoninstall', 'pscanrulesAlpha'])

        if zap_options:
            for zap_opt in zap_options.split(" "):
                params.append(zap_opt)

        try:
            cid = start_docker_zap('owasp/zap2docker-weekly', port, params, mount_dir)
            zap_ip = ipaddress_for_cid(cid)
            logging.debug('Docker ZAP IP Addr: ' + zap_ip)
        except OSError:
            logging.warning('Failed to start ZAP in docker :(')
            sys.exit(3)

    try:
        zap = ZAPv2(proxies={'http': 'http://' + zap_ip + ':' + str(port), 'https': 'http://' + zap_ip + ':' + str(port)})

        wait_for_zap_start(zap, timeout * 60)

        if context_file:
            # handle the context file, cant use base_dir as it might not have been set up
            res = zap.context.import_context('/zap/wrk/' + os.path.basename(context_file))
            if res.startswith("ZAP Error"):
                logging.error('Failed to load context file ' + context_file + ' : ' + res)

        zap_access_target(zap, target)

        if target.count('/') > 2:
            # The url can include a valid path, but always reset to spider the host
            target = target[0:target.index('/', 8)+1]

        time.sleep(2)

        # Create logged in session
        if auth_login_url:
            logging.debug ('Setup a new context')

            # create a new context
            zap.context.new_context('auth')

            # include everything below the target
            zap.context.include_in_context('auth', "\\Q" + target + "\\E.*")
            logging.debug ('Context - included ' + target + ".*")

            # set excluded URLs
            for exclude in auth_exclude_urls:
                zap.context.exclude_from_context('auth', exclude)
                logging.debug ('Context - excluded ' + exclude)

            # set the context in scope
            zap.context.set_context_in_scope('auth', True)
            zap.context.set_context_in_scope('Default Context', False)

            # configure proxy
            logging.debug ('Setup proxy for webdriver')
            PROXY = zap_ip + ':' + str(port)

            webdriver.DesiredCapabilities.FIREFOX['proxy'] = {
                "httpProxy":PROXY,
                "ftpProxy":PROXY,
                "sslProxy":PROXY,
                "proxyType":"manual"
            }

            # connect webdriver to Firefox
            profile = webdriver.FirefoxProfile()
            profile.accept_untrusted_certs = True # WARNING! Accept untrusted certs!
            profile.set_preference("browser.startup.homepage_override.mstone", "ignore")
            profile.set_preference("startup.homepage_welcome_url.additional", "about:blank")

            display = Display(visible=False, size=(1024, 768))
            display.start()

            logging.debug ('Run the webdriver for authentication')
            driver = webdriver.Firefox(profile)
            driver.implicitly_wait(30)

            # authenticate
            logging.debug ('Authenticate using webdriver ' + auth_login_url)
            driver.get(auth_login_url)

            if auth_username:
                driver.find_element_by_name(auth_username_field).clear()
                driver.find_element_by_name(auth_username_field).send_keys(auth_username)

            if auth_first_page:
                if auth_first_submit_field != '':
                    first_submit_xpath = "//*[@name='" + auth_first_submit_field + "' or @value='" + auth_first_submit_field +"']"
                    driver.find_element_by_name(first_submit_xpath).click()
                else:
                    # click on first button or input with "submit" type
                    driver.find_element_by_xpath("//*[@type='submit']").click()

            if auth_password:
                driver.find_element_by_name(auth_password_field).clear()
                driver.find_element_by_name(auth_password_field).send_keys(auth_password)

            if auth_submit_field != '':
                submit_xpath = "//*[@name='" + auth_submit_field + "' or @value='" + auth_submit_field +"']"
                driver.find_element_by_xpath(submit_xpath).click()
            else:
                # click on first button or input with "submit" type
                driver.find_element_by_xpath("//*[@type='submit']").click()

            # Create a new session using the aquired cookies from the authentication
            logging.debug ('Create an authenticated session')
            zap.httpsessions.create_empty_session(target, 'auth-session')

            # add all found cookies as session cookies
            for cookie in driver.get_cookies():
                zap.httpsessions.set_session_token_value(target, 'auth-session', cookie['name'], cookie['value'])
                logging.debug ('Cookie found: ' + cookie['name'] + ' - Value: ' + cookie['value'])

            # Mark the session as active
            zap.httpsessions.set_active_session(target, 'auth-session')
            logging.debug ('Active session: ' + zap.httpsessions.active_session(target))

            driver.quit()
            display.stop()

        # Spider target
        if auth_login_url:
            authenticated_spider=True
        else:
            authenticated_spider=False

        zap_spider(zap, target, authenticated_spider)

        if (ajax):
            zap_ajax_spider(zap, target, mins)

        if (delay):
            start_scan = datetime.now()
            while ((datetime.now() - start_scan).seconds < delay):
                time.sleep(5)
                logging.debug('Delay passive scan check ' + str(delay - (datetime.now() - start_scan).seconds) + ' seconds')

        zap_wait_for_passive_scan(zap, timeout * 60)

        # Print out a count of the number of urls
        num_urls = len(zap.core.urls)
        if num_urls == 0:
            logging.warning('No URLs found - is the target URL accessible? Local services may not be accessible from the Docker container')
        else:
            if detailed_output:
                print('Total of ' + str(num_urls) + ' URLs')

            alert_dict = zap_get_alerts(zap, target, blacklist, out_of_scope_dict)

            all_rules = zap.pscan.scanners
            all_dict = {}
            for rule in all_rules:
                plugin_id = rule.get('id')
                if plugin_id in blacklist:
                    continue
                all_dict[plugin_id] = rule.get('name')

            if generate:
                # Create the config file
                with open(base_dir + generate, 'w') as f:
                    f.write('# zap-baseline rule configuration file\n')
                    f.write('# Change WARN to IGNORE to ignore rule or FAIL to fail if rule matches\n')
                    f.write('# Only the rule identifiers are used - the names are just for info\n')
                    f.write('# You can add your own messages to each rule by appending them after a tab on each line.\n')
                    for key, rule in sorted(all_dict.items()):
                        f.write(key + '\tWARN\t(' + rule + ')\n')

            # print out the passing rules
            pass_dict = {}
            for rule in all_rules:
                plugin_id = rule.get('id')
                if plugin_id in blacklist:
                    continue
                if (plugin_id not in alert_dict):
                    pass_dict[plugin_id] = rule.get('name')

            if min_level == zap_conf_lvls.index("PASS") and detailed_output:
                for key, rule in sorted(pass_dict.items()):
                    print('PASS: ' + rule + ' [' + key + ']')

            pass_count = len(pass_dict)

            # print out the ignored rules
            ignore_count, not_used = print_rules(alert_dict, 'IGNORE', config_dict, config_msg, min_level,
                inc_ignore_rules, True, detailed_output, {})

            # print out the info rules
            info_count, not_used = print_rules(alert_dict, 'INFO', config_dict, config_msg, min_level,
                inc_info_rules, info_unspecified, detailed_output, in_progress_issues)

            # print out the warning rules
            warn_count, warn_inprog_count = print_rules(alert_dict, 'WARN', config_dict, config_msg, min_level,
                inc_warn_rules, not info_unspecified, detailed_output, in_progress_issues)

            # print out the failing rules
            fail_count, fail_inprog_count = print_rules(alert_dict, 'FAIL', config_dict, config_msg, min_level,
                inc_fail_rules, True, detailed_output, in_progress_issues)

            if report_html:
                # Save the report
                write_report(base_dir + report_html, zap.core.htmlreport())

            if report_json:
                # Save the report
                write_report(base_dir + report_json, zap._request_other(zap.base_other + 'core/other/jsonreport/'))

            if report_md:
                # Save the report
                write_report(base_dir + report_md, zap.core.mdreport())

            if report_xml:
                # Save the report
                write_report(base_dir + report_xml, zap.core.xmlreport())

            print('FAIL-NEW: ' + str(fail_count) + '\tFAIL-INPROG: ' + str(fail_inprog_count) +
                '\tWARN-NEW: ' + str(warn_count) + '\tWARN-INPROG: ' + str(warn_inprog_count) +
                '\tINFO: ' + str(info_count) + '\tIGNORE: ' + str(ignore_count) + '\tPASS: ' + str(pass_count))

        # Stop ZAP
        zap.core.shutdown()

    except IOError as e:
        if hasattr(e, 'args') and len(e.args) > 1:
            errno, strerror = e.args
            print("ERROR " + str(strerror))
            logging.warning('I/O error(' + str(errno) + '): ' + str(strerror))
        else:
            print("ERROR %s" % e)
            logging.warning('I/O error: ' + str(e))
        dump_log_file(cid)

    except:
        print("ERROR " + str(sys.exc_info()[0]))
        logging.warning('Unexpected error: ' + str(sys.exc_info()[0]))
        dump_log_file(cid)

    if not running_in_docker():
        stop_docker(cid)

    if fail_count > 0:
        sys.exit(1)
    elif warn_count > 0:
        sys.exit(2)
    elif pass_count > 0:
        sys.exit(0)
    else:
        sys.exit(3)


if __name__ == "__main__":
    main(sys.argv[1:])
