#!/usr/bin/env python
# Copyright 2011 Daniel James
# Distributed under the Boost Software License, Version 1.0.
# (See accompanying file LICENSE_1_0.txt or http://www.boost.org/LICENSE_1_0.txt)

import boost_site.state, boost_site.util
import os, sys, hashlib, xml.dom.minidom, re, fnmatch, subprocess, tempfile, time

class Pages:
    """ Tracks which items in an rss feed have been updated.

    Stores meta data about the quickbook file, including the signature
    of the quickbook file.
    """
    def __init__(self, hash_file):
        self.hash_file = hash_file
    
        # Map of quickbook filename to Page
        self.pages = {}
        
        if(os.path.isfile(hash_file)):
            hashes = boost_site.state.load(hash_file)
            for qbk_file in hashes:
                record = hashes[qbk_file]
                self.pages[qbk_file] = Page(qbk_file, record)

    def save(self):
        save_hashes = {}
        for x in self.pages:
            save_hashes[x] = self.pages[x].state()
        boost_site.state.save(save_hashes, self.hash_file)

    def add_qbk_file(self, qbk_file, location, page_data):
        if sys.version_info < (3,0):
            file = open(qbk_file, 'r')
            qbk_hash = hashlib.sha256(file.read()).hexdigest()
            file.close()
        else:
            file = open(qbk_file, 'rb')
            qbk_hash = hashlib.sha256(file.read().replace(bytes([13,10]), bytes([10]))).hexdigest()
            file.close()

        record = None

        if qbk_file not in self.pages:
            self.pages[qbk_file] = record = \
                Page(qbk_file)
        else:
            record = self.pages[qbk_file]
            if record.dir_location:
                assert record.dir_location == location
            if record.qbk_hash == qbk_hash:
                return
            if record.page_state != 'new':
                record.page_state = 'changed'

        record.qbk_hash = qbk_hash
        record.dir_location = location
        if 'type' in page_data:
            record.type = page_data['type']
        else:
            record.type = 'page'
        if record.type not in ['release', 'page']:
            throw ("Unknown record type: " + record.type)

    def convert_quickbook_pages(self, refresh = False):
        try:
            subprocess.check_call(['quickbook', '--version'])
        except:
            print("Problem running quickbook, will not convert quickbook articles.")
            return
        
        bb_parser = boost_site.boostbook_parser.BoostBookParser()
    
        for page in self.pages:
            page_data = self.pages[page]
            if page_data.page_state or refresh:
                xml_file = tempfile.mkstemp('', '.xml')
                os.close(xml_file[0])
                xml_filename = xml_file[1]
                try:
                    print("Converting " + page + ":")
                    subprocess.check_call(['quickbook', '--output-file', xml_filename, '-I', 'feed', page])
                    page_data.load(bb_parser.parse(xml_filename), refresh)
                finally:
                    os.unlink(xml_filename)

                template_vars = {
                    'history_style' : '',
                    'full_title_xml' : page_data.full_title_xml,
                    'title_xml' : page_data.title_xml,
                    'note_xml' : '',
                    'web_date' : page_data.web_date(),
                    'documentation_para' : '',
                    'download_table' : page_data.download_table(),
                    'description_xml' : page_data.description_xml
                }

                if page_data.type == 'release' and 'released' not in page_data.flags and 'beta' not in page_data.flags:
                    template_vars['note_xml'] = """
                        <div class="section-note"><p>Note: This release is
                        still under development. Please don't use this page as
                        a source of information, it's here for development
                        purposes only. Everything is subject to
                        change.</p></div>"""

                if page_data.documentation:
                    template_vars['documentation_para'] = '<p><a href="' + boost_site.util.htmlencode(page_data.documentation) + '">Documentation</a>'

                if(page_data.location.startswith('users/history/')):
                    template_vars['history_style'] = """
  <style type="text/css">
/*<![CDATA[*/
  #content .news-description ul {
    list-style: none;
  }
  #content .news-description ul ul {
    list-style: circle;
  }
  /*]]>*/
  </style>
"""

                boost_site.util.write_template(page_data.location,
                    'site-tools/templates/entry-template.html',
                    template_vars)

    def match_pages(self, patterns, count = None, sort = True):
        """
            patterns is a list of strings, containing a glob followed
            by required flags, separated by '|'. The syntax will probably
            change in the future.
        """
        filtered = set()
        for pattern in patterns:
            pattern_parts = pattern.split('|')
            matches = [x for x in
                fnmatch.filter(list(self.pages.keys()), pattern_parts[0])
                if self.pages[x].is_published(pattern_parts[1:])]
            filtered = filtered | set(matches)

        entries = [self.pages[x] for x in filtered]

        if sort:
            entries = sorted(entries, key = lambda x: x.last_modified, reverse=True)
        if count:
            entries = entries[:count]
        return entries

def hash_dom_node(node):
    return hashlib.sha256(node.toxml('utf-8')).hexdigest()

class Page:
    def __init__(self, qbk_file, attrs = None):
        self.qbk_file = qbk_file

        if not attrs: attrs = { 'page_state' : 'new' }

        self.type = attrs.get('type', None)
        self.page_state = attrs.get('page_state', None)
        self.release_status = attrs.get('release_status', None)
        self.dir_location = attrs.get('dir_location', None)
        self.location = attrs.get('location', None)
        self.id = attrs.get('id', None)
        self.title_xml = attrs.get('title', None)
        self.purpose_xml = attrs.get('purpose', None)
        self.notice_xml = attrs.get('notice', None)
        self.notice_url = attrs.get('notice_url', None)
        self.last_modified = attrs.get('last_modified')
        self.pub_date = attrs.get('pub_date')
        self.download_item = attrs.get('download')
        self.download_basename = attrs.get('download_basename')
        self.documentation = attrs.get('documentation')
        self.final_documentation = attrs.get('final_documentation')
        self.qbk_hash = attrs.get('qbk_hash')

        self.loaded = False

        self.initialise()

    def initialise(self):
        self.flags = set()
        self.full_title_xml = self.title_xml

        if self.type == 'release':
            if not self.release_status and self.pub_date != 'In Progress':
                self.release_status = 'released'
            if not self.release_status:
                self.release_status = 'dev'
            status_parts = self.release_status.split(' ', 2)
            if status_parts[0] not in ['released', 'beta', 'dev']:
                print("Error: Unknown release status: " + self.release_status)
                self.release_status = None
            if self.release_status:
                self.flags.add(status_parts[0])
            if ('beta' in self.flags):
                self.full_title_xml = self.full_title_xml + ' ' + self.release_status
            elif ('released' not in self.flags):
                self.full_title_xml = self.full_title_xml + ' - work in progress'

    def state(self):
        return {
            'type': self.type,
            'page_state': self.page_state,
            'release_status': self.release_status,
            'dir_location': self.dir_location,
            'location': self.location,
            'id' : self.id,
            'title': self.title_xml,
            'purpose': self.purpose_xml,
            'notice': self.notice_xml,
            'notice_url': self.notice_url,
            'last_modified': self.last_modified,
            'pub_date': self.pub_date,
            'download': self.download_item,
            'download_basename': self.download_basename,
            'documentation': self.documentation,
            'final_documentation': self.final_documentation,
            'qbk_hash': self.qbk_hash
        }

    def load(self, values, refresh = False):
        assert self.dir_location or refresh
        assert not self.loaded
    
        self.title_xml = boost_site.util.fragment_to_string(values['title_fragment'])
        self.purpose_xml = boost_site.util.fragment_to_string(values['purpose_fragment'])
        self.notice_xml = boost_site.util.fragment_to_string(values['notice_fragment']) \
            if values['notice_fragment'] else None
        self.notice_url = values['notice_url']

        self.pub_date = values['pub_date']
        self.last_modified = values['last_modified']
        self.download_item = values['download_item']
        self.download_basename = values['download_basename']
        self.documentation = values['documentation']
        self.final_documentation = values['final_documentation']
        self.id = values['id']
        if not self.id:
            self.id = re.sub('[\W]', '_', self.title_xml).lower()
        if self.dir_location:
            self.location = self.dir_location + self.id + '.html'
            self.dir_location = None
            self.page_state = None
        self.release_status = values['status_item']

        self.loaded = True

        self.initialise()

        if 'released' not in self.flags and self.documentation:
            doc_matcher = re.compile('^/(?:libs/|doc/html/)')
            doc_prefix = self.documentation.rstrip('/')
            boost_site.util.transform_links(values['description_fragment'],
                lambda x: doc_matcher.match(x) and \
                    doc_prefix + x or x)

            if self.final_documentation:
                link_pattern = re.compile('^' + self.final_documentation.rstrip('/') + '/')
                replace = doc_prefix + '/'
                boost_site.util.transform_links(values['description_fragment'],
                    lambda x: link_pattern.sub(replace, x, 1))

        self.description_xml = boost_site.util.fragment_to_string(values['description_fragment'])

    def web_date(self):
        if self.pub_date == 'In Progress':
            return self.pub_date
        else:
            release_time = time.gmtime(self.last_modified)
            return time.strftime(
                    '%B %e' +
                    number_suffix(release_time.tm_mday) +
                    ', %Y %H:%M GMT', release_time)

    def download_table(self):
        if(not self.download_item):
            return ''
        if self.type == 'release' and ('beta' not in self.flags and 'released' not in self.flags):
            return ''

        downloads = None

        if self.download_basename:
            downloads = {
                'unix' : [self.download_basename + '.tar.bz2', self.download_basename + '.tar.gz'],
                'windows' : [self.download_basename + '.7z', self.download_basename + '.zip']
            }
        else:
            match = re.match('.*/boost/(\d+)\.(\d+)\.(\d+)/', self.download_item)
            if(match):
                major = int(match.group(1))
                minor = int(match.group(2))
                point = int(match.group(3))
                base_name = 'boost_' + match.group(1) + '_' + match.group(2) + '_' + match.group(3)
    
                # Pick which files are available by examining the version number.
                # This could possibly be meta-data in the rss feed instead of being
                # hardcoded here.

                # TODO: Key order hardcoded later.

                downloads = {
                    'unix' : [base_name + '.tar.bz2', base_name + '.tar.gz'],
                    'windows' : []
                }

                if(major == 1 and minor >= 32 and minor <= 33):
                    downloads['windows'].append(base_name + '.exe')
                elif(major > 1 or minor > 34 or (minor == 34 and point == 1)):
                    downloads['windows'].append(base_name + '.7z')
                downloads['windows'].append(base_name + '.zip')

        if downloads is not None:
            # Print the download table.
            
            output = ''
            output = output + '<table class="download-table">'
            if 'beta' in self.flags:
                output = output + '<caption>Beta Downloads</caption>'
            else:
                output = output + '<caption>Downloads</caption>'
            output = output + '<tr><th scope="col">Platform</th><th scope="col">File</th></tr>'
    
            for platform in ['unix', 'windows']:
                files = downloads[platform]
                output += "\n"
                output += '<tr><th scope="row"'
                if(len(files) > 1):
                    output += ' rowspan="' + str(len(files)) + '"';
                output += '>' + boost_site.util.htmlencode(platform) + '</th>'
                output += '</tr><tr>'.join(
                    '<td><a href="' + boost_site.util.htmlencode(self.download_item + file + '/download') + '">' + boost_site.util.htmlencode(file) + '</a></td>'
                    for file in files
                )
                output += '</tr>'
    
            output += '</table>'
            return output
        else:
            # If the link didn't match the normal version number pattern
            # then just use the old fashioned link to sourceforge. */
    
            output = '<p><span class="news-download"><a href="' + \
                boost_site.util.htmlencode(self.download_item) + \
                '">'

            if 'beta' in self.flags:
                output = output + 'Download this beta release.'
            else:
                output = output + 'Download this release.'

            output = output + '</a></span></p>'

            return output

    def is_published(self, flags):
        if self.page_state == 'new':
            return False
        for flag in flags:
            if flag not in self.flags:
                return False
        return True

def number_suffix(x):
    x = x % 100
    if x // 10 == 1:
        return "th"
    else:
        return ["th", "st", "nd", "rd", "th", "th", "th", "th", "th", "th"][x % 10]
