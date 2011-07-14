# -*- coding: utf-8 -*-

# Copyright 2011 Fanficdownloader team
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import re
import datetime
import time
import logging
import urllib
import urllib2 as u2
import urlparse as up

try:
    from google.appengine.api import apiproxy_stub_map
    def urlfetch_timeout_hook(service, call, request, response):
        if call != 'Fetch':
            return
        # Make the default deadline 10 seconds instead of 5.
        if not request.has_deadline():
            request.set_deadline(10.0)

    apiproxy_stub_map.apiproxy.GetPreCallHooks().Append(
        'urlfetch_timeout_hook', urlfetch_timeout_hook, 'urlfetch')
    logging.info("Hook to make default deadline 10.0 installed.")
except:
    pass
    #logging.info("Hook to make default deadline 10.0 NOT installed--not using appengine")

from fanficdownloader.story import Story
from fanficdownloader.configurable import Configurable
from fanficdownloader.htmlcleanup import removeEntities, removeAllEntities, stripHTML
from fanficdownloader.exceptions import InvalidStoryURL

class BaseSiteAdapter(Configurable):

    @classmethod
    def matchesSite(cls,site):
        return site in cls.getAcceptDomains()

    @classmethod
    def getAcceptDomains(cls):
        return [cls.getSiteDomain()]

    def validateURL(self):
        return re.match(self.getSiteURLPattern(), self.url)

    def __init__(self, config, url):
        Configurable.__init__(self, config)
        self.addConfigSection(self.getSiteDomain())
        self.addConfigSection("overrides")
        
        self.opener = u2.build_opener(u2.HTTPCookieProcessor())
        self.storyDone = False
        self.metadataDone = False
        self.story = Story()
        self.story.setMetadata('site',self.getSiteDomain())
        self.story.setMetadata('dateCreated',datetime.datetime.now())
        self.chapterUrls = [] # tuples of (chapter title,chapter url)
        self.chapterFirst = None
        self.chapterLast = None
        ## order of preference for decoding.
        self.decode = ["utf8",
                       "Windows-1252"] # 1252 is a superset of
                                       # iso-8859-1.  Most sites that
                                       # claim to be iso-8859-1 (and
                                       # some that claim to be utf8)
                                       # are really windows-1252.
        self._setURL(url)
        if not self.validateURL():
            raise InvalidStoryURL(url,
                                  self.getSiteDomain(),
                                  self.getSiteExampleURLs())        

    def _setURL(self,url):
        self.url = url
        self.parsedUrl = up.urlparse(url)
        self.host = self.parsedUrl.netloc
        self.path = self.parsedUrl.path        
        self.story.setMetadata('storyUrl',self.url)

    def _decode(self,data):
        for code in self.decode:
            try:
                return data.decode(code)
            except:
                logging.debug("code failed:"+code)
                pass
        logging.info("Could not decode story, tried:%s Stripping non-ASCII."%self.decode)
        return "".join([x for x in data if ord(x) < 128])

    # Assumes application/x-www-form-urlencoded.  parameters, headers are dict()s
    def _postUrl(self, url, parameters={}, headers={}):
        if self.getConfig('slow_down_sleep_time'):
            time.sleep(float(self.getConfig('slow_down_sleep_time')))

        ## u2.Request assumes POST when data!=None.  Also assumes data
        ## is application/x-www-form-urlencoded.
        if 'Content-type' not in headers:
            headers['Content-type']='application/x-www-form-urlencoded'
        if 'Accept' not in headers:
            headers['Accept']="text/html,*/*"
        req = u2.Request(url,
                         data=urllib.urlencode(parameters),
                         headers=headers)
        return self._decode(self.opener.open(req).read())

    # parameters is a dict()
    def _fetchUrl(self, url, parameters=None):
        if self.getConfig('slow_down_sleep_time'):
            time.sleep(float(self.getConfig('slow_down_sleep_time')))

        excpt=None
        for sleeptime in [0, 0.5, 4, 9]:
            time.sleep(sleeptime)	
            try:
                if parameters:
                    return self._decode(self.opener.open(url,urllib.urlencode(parameters)).read())
                else:
                    return self._decode(self.opener.open(url).read())
            except Exception, e:
                excpt=e
                logging.warn("Caught an exception reading URL: %s  Exception %s."%(unicode(url),unicode(e)))
                
        logging.error("Giving up on %s" %url)
        logging.exception(excpt)
        raise(excpt)

    # Limit chapters to download.  Input starts at 1, list starts at 0
    def setChaptersRange(self,first=None,last=None):
        if first:
            self.chapterFirst=int(first)-1
        if last:
            self.chapterLast=int(last)-1
    
    # Does the download the first time it's called.
    def getStory(self):
        if not self.storyDone:
            self.getStoryMetadataOnly()
            for index, (title,url) in enumerate(self.chapterUrls):
                if (self.chapterFirst!=None and index < self.chapterFirst) or \
                        (self.chapterLast!=None and index > self.chapterLast):
                    self.story.addChapter(removeEntities(title),
                                          None)
                else:
                    self.story.addChapter(removeEntities(title),
                                          removeEntities(self.getChapterText(url)))
            self.storyDone = True
        return self.story

    def getStoryMetadataOnly(self):
        if not self.metadataDone:
            self.extractChapterUrlsAndMetadata()
            self.metadataDone = True
        return self.story

    ###############################
    
    @staticmethod
    def getSiteDomain():
        "Needs to be overriden in each adapter class."
        return 'no such domain'
    
    ## URL pattern validation is done *after* picking an adaptor based
    ## on domain instead of *as* the adaptor selector so we can offer
    ## the user example(s) for that particular site.
    ## Override validateURL(self) instead if you need more control.
    def getSiteURLPattern(self):
        "Used to validate URL.  Should be override in each adapter class."
        return '^http://'+re.escape(self.getSiteDomain())
    
    def getSiteExampleURLs(self):
        """
        Needs to be overriden in each adapter class.  It's the adapter
        writer's responsibility to make sure the example(s) pass the
        URL validate.
        """
        return 'no such example'
    
    def extractChapterUrlsAndMetadata(self):
        "Needs to be overriden in each adapter class.  Populates self.story metadata and self.chapterUrls"
        pass

    def getChapterText(self, url):
        "Needs to be overriden in each adapter class."
        pass
        
def makeDate(string,format):
    return datetime.datetime.strptime(string,format)

acceptable_attributes = ['href','name']

# this gives us a unicode object, not just a string containing bytes.
# (I gave soup a unicode string, you'd think it could give it back...)
def utf8FromSoup(soup):
    for t in soup.findAll(recursive=True):
        for attr in t._getAttrMap().keys():
            if attr not in acceptable_attributes:
                del t[attr] ## strip all tag attributes except href and name
        # these are not acceptable strict XHTML.  But we do already have 
	# CSS classes of the same names defined in constants.py
	if t.name in ('u'):
            t['class']=t.name
            t.name='span'
        if t.name in ('center'):
            t['class']=t.name
            t.name='div'
	# removes paired, but empty tags.
        if t.string != None and len(t.string.strip()) == 0 :
            t.extract()
    return soup.__str__('utf8').decode('utf-8')