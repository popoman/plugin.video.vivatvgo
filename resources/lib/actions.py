﻿# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import xbmc
import base64
import urllib
import xbmcgui
import pickle
import requests
import traceback
from datetime import datetime, timedelta
from collections import OrderedDict
from kodibgcommon.utils import *

reload(sys)  
sys.setdefaultencoding('utf8')

profile_dir = get_profile_dir()
cookie_file = os.path.join(profile_dir, '.cookies')
channels_file = os.path.join(profile_dir, '.channels')
programs_file = os.path.join(profile_dir, '.programs')
response_file = os.path.join(profile_dir, 'last_response.txt')

def save_cookies(s):
  with open(cookie_file, 'w') as f:
    f.truncate()
    pickle.dump(s.cookies._cookies, f)
  return True

def load_cookies():
  jar = requests.cookies.RequestsCookieJar()
  if os.path.isfile(cookie_file):
    with open(cookie_file) as f:
      cookies = pickle.load(f)
      if cookies:
        jar._cookies = cookies
        return jar
  return jar
  
def __request(url, payload=None):
  headers = {'User-Agent': 'okhttp/2.5.0', 'USER_AGENT': 'android'}
  method = "POST" if payload else "GET"
  log("**************************************************")
  log("%s %s" % (method, url))
  for key,val in headers.items():
    log("%s: %s" % (key, val))
  if payload:
    res = session.post(url, json=payload, headers=headers)
    ## Obfuscate password in logs
    _pass = payload.get("password")
    if _pass:
      payload["password"] = "********"
    log("%s" % json.dumps(payload))
  else:
    res = session.get(url, headers=headers)
  if settings.debug:
    with open(response_file, "w") as w:
      w.write(res.text)
  return res
  
def login():
  url =  base64.b64decode("aHR0cDovL3R2Z28udml2YWNvbS5iZzo4MDgyL0VEUy9KU09OL0xvZ2luP1VzZXJJRD0lcw==") % settings.username
  res = __request(url)
  settings.url = res.json()["epgurl"]
  
  url = get_url(base64.b64decode("Vml2YWNvbVNTT0F1dGg="))
  post_data = {"password": settings.password, "userName": settings.username}
  res = __request(url, post_data)
  msg = "Неочаквана грешка. Моля проверете лога"
  if res.json().get("retcode") and res.json()["retcode"] != "0":
    if res.json().get("retmsgBG"):
      msg = res.json()["retmsgBG"]
    elif res.json().get("retmsg"):
      msg = res.json()["retmsg"]
    elif res.json().get("desc"):
      msg = res.json()["desc"]
    
    log(res.text)
    
    command = "Notification(%s,%s,%s)" % ("Грешка", msg.encode('utf-8'), 5000)
    xbmc.executebuiltin(command)
    return False

  settings.checksum = res.json()[base64.b64decode("dml2YWNvbVN1YnNjcmliZXJz")][0]["checksum"]
  settings.subscriberId = res.json()[base64.b64decode("dml2YWNvbVN1YnNjcmliZXJz")][0]["subscriberId"]

  post_data = {"checksum":settings.checksum,"mac":settings.guid,"subscriberId":settings.subscriberId,"terminaltype":"NoCAAndroidPhone","userName":settings.username}
  res = __request(url, post_data)
  settings.subscriberPassword = res.json()["users"][0]["password"]
  
  save_cookies(session)
  
  return True

def get_channels():
  try:
    if login():
      post_data = {"id": settings.subscriberId, "password": settings.subscriberPassword}
      res = __request(get_url(base64.b64decode("U3dpdGNoUHJvZmlsZQ==")), post_data)
      if settings.debug:
        with open(response_file, "w") as w:
          w.write(res.text)     
      
      channels = {}
      if settings.rebuild_cache or not os.path.isfile(channels_file):
        progress_bar = xbmcgui.DialogProgressBG()
        progress_bar.create(heading="Канали")
        progress_bar.update(5, "Изграждане на списък с канали...")
        res = __request(get_url(base64.b64decode("QWxsQ2hhbm5lbA==")), post_data)
        if not res.json().get("channellist"):
          settings.rebuild_cache = True
          return None
        
        progress_bar.update(50, "Getting channels...")
        settings.rebuild_cache = False
        i = 0
        p = 50
        for item in res.json()["channellist"]:
          p += 5
          progress_bar.update(p, "Изграждане на списък с канали...")
          if item.get("issubscribed") == "1":
            channel = {}
            i += 1
            channel["name"] = item["name"]
            channel["order"] = i
            channel["mediaid"] = item["mediaid"]
            channel["logo"] = item.get("logo").get("url")
            channels[item["id"]] = channel
          
        with open(channels_file, "w") as w:
          w.write(json.dumps(channels, ensure_ascii=False))
        
        if progress_bar:
          progress_bar.close()
      else: #load channels from cache
        channels = json.load(open(channels_file))
        
      channels = OrderedDict(sorted(channels.iteritems(), key=lambda c: c[1]['order'], reverse=False))
      log("%s channels found" % len(channels))
      return channels
    else:
      return None
  except:
    log(traceback.format_exc(sys.exc_info()), 4)
    return None

def get_channel(id):
  try:
    channels = json.load(open(channels_file))
    log("Getting channel with id %s" % id)
    channel = channels.get(id)
    if channel:
      streams = get_stream(id, channel["mediaid"], 2, "VIDEO_CHANNEL")
      playpaths = []
      try: playpaths = streams.split("|")
      except:
        try: playpaths[0] = streams
        except: log("No playpath found for channel %s" % channel["name"], 4)
      channel["playpaths"] = playpaths
      
      #EPG
      try:
        now = datetime.now()
        begintime = now.strftime("%Y%m%d%H%M%S")
        post_data = {"begintime": begintime, "channelid":id, "count": 1, "offset":0, "type":2}
        res = __request(get_url("PlayBillList"), post_data)
        __json = res.json().get("playbilllist")[0]
        
        channel["desc"] = ""
        
        start = "%s:%s" % (__json["starttime"][8:10], __json["starttime"][11:13])
        end = "%s:%s" % (__json["endtime"][8:10], __json["endtime"][11:13])
        if start:
          channel["desc"] += " %s" % start
        if end:
          channel["desc"] += " - %s" % end
          
        channel["desc"] += " %s" % __json.get("name")

        if __json.get("introduce") and __json["introduce"] != "":
          intro = __json["introduce"].replace(__json["name"], "")
          if intro.rstrip() != "":
            channel["desc"] += ", %s" % intro
      except Exception as er:
        log(er, 4)
        
      return channel  
    log("Channel with id %s not found" % id, 4)
  except:
    log(traceback.format_exc(sys.exc_info()), 4)
  return None
    
def get_dates():
  now = datetime.now()
  dates = []
  for i in range (0, 7):
    then = now - timedelta(days=i)
    date = then.strftime("%d-%m-%Y")
    dates.append(date)
  return dates

  
def get_recorded_programs(id, date):
  log("Getting EPG")
  try: # second use bug https://forum.kodi.tv/showthread.php?tid=112916
    dt = datetime.strptime(date, "%d-%m-%Y")
  except TypeError:
    dt = datetime.fromtimestamp(time.mktime(time.strptime(date, "%d-%m-%Y")))
  begintime = dt.strftime("%Y%m%d000000")
  endtime = dt.strftime("%Y%m%d240000")
  
  post_data = {"begintime":begintime,"channelid":id,"count":"1000","endtime":endtime,"offset":0,"type":2}
  res = __request(get_url("PlayBillList"), post_data)
  if settings.debug:
    with open(programs_file, "w") as w:
      w.write(res.text)
  
  if res.json().get("retcode") and res.json()["retcode"] != "0":
    if res.json().get("desc"):
      command = "Notification(%s,%s,%s)" % ("Error", res.json()["desc"].encode('utf-8'), 5000)
      xbmc.executebuiltin(command) 
    return None
  else:
    log("%s programs found for channel id %s" % (res.json().get("counttotal"), id))
    return res.json().get("playbilllist")
  
def get_stream(id, mediaId, businessType=5, conentType="PROGRAM"):
  res = None
  try:
    post_data = {"businessType":businessType,"contentId":id,"contentType":conentType,"mediaId":mediaId,"priceType":"-1","pvrId":0}
    res = __request(get_url(base64.b64decode("QXV0aG9yaXplQW5kUGxheQ==")), post_data)
    playurl = res.json().get("playUrl")
    if playurl:
      log("Found playurl: %s" % playurl)
    else:
      log("playurl not found")
      
  except Exception as er:
    log(er, 4)
    if res:
      log(res.text)
  return playurl

def get_url(name):  
  return settings.url + base64.b64decode("L0VQRy9KU09OLw==") + name
  
session = requests.session()
session.cookies = load_cookies()