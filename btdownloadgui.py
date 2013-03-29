#!/usr/bin/env python

# Written by Bram Cohen and Myers Carpenter
# Modifications by various people
# see LICENSE.txt for license information

import sys
import os
import re
import time
import random
import socket
import hashlib
import threading
import traceback
from binascii import hexlify
from webbrowser import open_new
from StringIO import StringIO
from BitTornado.download_bt1 import BT1Download, parse_params, get_usage, \
    get_response
from BitTornado.RawServer import RawServer
from BitTornado.SocketHandler import UPnP_ERROR
from BitTornado.ConnChoice import connChoices, connChoiceList
from BitTornado.ConfigReader import configReader
from BitTornado.bencode import bencode
from BitTornado.natpunch import UPnP_test
from BitTornado.clock import clock
from BitTornado import version, createPeerID, report_email

try:
    from wxPython import wx
except:
    print 'wxPython is not installed or has not been installed properly.'
    sys.exit(1)

PROFILER = False
WXPROFILER = False

try:
    wx.wxFULL_REPAINT_ON_RESIZE
except:
    wx.wxFULL_REPAINT_ON_RESIZE = 0        # fix for wx pre-2.5

# Note to packagers: edit OLDICONPATH in BitTornado/ConfigDir.py


def hours(n):
    if n == 0:
        return 'download complete'
    try:
        n = int(n)
        assert n >= 0 and n < 5184000  # 60 days
    except:
        return '<unknown>'
    m, s = divmod(n, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return '%d hour(s) %02d min %02d sec' % (h, m, s)
    else:
        return '%d min %02d sec' % (m, s)


def size_format(s):
    if (s < 1024):
        r = '{:d}B'.format(s)
    elif (s < 1048576):
        r = '{:d}KiB'.format(s / 1024)
    elif (s < 1073741824L):
        r = '{:d}MiB'.format(s / (1 << 20))
    elif (s < 1099511627776L):
        r = '{:.2f}GiB'.format(float(s) / (1 << 30))
    else:
        r = '{:.2f}TiB'.format(float(s) / (1 << 40))
    return(r)


def comma_format(s):
    r = str(s)
    for i in range(len(r) - 3, 0, -3):
        r = r[:i] + ',' + r[i:]
    return(r)

wxEVT_INVOKE = wx.wxNewEventType()


def EVT_INVOKE(win, func):
    win.Connect(-1, -1, wxEVT_INVOKE, func)


class InvokeEvent(wx.wxPyEvent):
    def __init__(self, func=None, args=None, kwargs=None):
        super(InvokeEvent, self).__init__()
        self.SetEventType(wxEVT_INVOKE)
        self.func = func
        self.args = args
        self.kwargs = kwargs


class DownloadInfoFrame:
    def __init__(self, flag, configfile):
        self._errorwindow = None
        try:
            self.FONT = configfile.config['gui_font']
            self.default_font = wx.wxFont(self.FONT, wx.wxDEFAULT, wx.wxNORMAL,
                                          wx.wxNORMAL, False)
            frame = wx.wxFrame(None, -1, 'BitTorrent ' + version + ' download',
                               style=wx.wxDEFAULT_FRAME_STYLE |
                               wx.wxFULL_REPAINT_ON_RESIZE)
            self.flag = flag
            self.configfile = configfile
            self.configfileargs = configfile.config
            self.uiflag = threading.Event()
            self.fin = False
            self.aboutBox = None
            self.detailBox = None
            self.advBox = None
            self.creditsBox = None
            self.statusIconHelpBox = None
            self.reannouncelast = 0
            self.spinlock = 0
            self.scrollock = 0
            self.lastError = 0
            self.spewwait = clock()
            self.config = None
            self.updateSpinnerFlag = 0
            self.updateSliderFlag = 0
            self.statusIconValue = ' '
            self.iconized = 0
            self.taskbaricon = False
            self.checking = None
            self.activity = 'Starting up...'
            self.firstupdate = True
            self.shuttingdown = False
            self.ispaused = False
            self.bgalloc_periods = 0
            self.gui_fractiondone = None
            self.fileList = None
            self.lastexternalannounce = ''
            self.refresh_details = False
            self.lastuploadsettings = 0
            self.old_download = 0
            self.old_upload = 0
            self.old_ratesettings = None
            self.current_ratesetting = None
            self.gaugemode = None
            self.autorate = False

            self.filename = None
            self.dow = None
            if sys.platform == 'win32':
                self.invokeLaterEvent = InvokeEvent()
                self.invokeLaterList = []

            wx.wxInitAllImageHandlers()
            self.basepath = self.configfile.getIconDir()
            self.icon = wx.wxIcon(os.path.join(self.basepath, 'icon_bt.ico'),
                                  wx.wxBITMAP_TYPE_ICO)
            self.finicon = wx.wxIcon(os.path.join(self.basepath,
                                                  'icon_done.ico'),
                                     wx.wxBITMAP_TYPE_ICO)
            self.statusIconFiles = {
                'startup':       os.path.join(self.basepath, 'white.ico'),
                'disconnected':  os.path.join(self.basepath, 'black.ico'),
                'noconnections': os.path.join(self.basepath, 'red.ico'),
                'nocompletes':   os.path.join(self.basepath, 'blue.ico'),
                'noincoming':    os.path.join(self.basepath, 'yellow.ico'),
                'allgood':       os.path.join(self.basepath, 'green.ico'),
            }
            self.statusIcons = {}
            self.filestatusIcons = wx.wxImageList(16, 16)
            self.filestatusIcons.Add(wx.wxBitmap(os.path.join(self.basepath,
                                     'black1.ico'), wx.wxBITMAP_TYPE_ICO))
            self.filestatusIcons.Add(wx.wxBitmap(os.path.join(self.basepath,
                                     'yellow1.ico'), wx.wxBITMAP_TYPE_ICO))
            self.filestatusIcons.Add(wx.wxBitmap(os.path.join(self.basepath,
                                     'green1.ico'), wx.wxBITMAP_TYPE_ICO))

            self.allocbuttonBitmap = wx.wxBitmap(
                os.path.join(self.basepath, 'alloc.gif'), wx.wxBITMAP_TYPE_GIF)

            self.starttime = clock()

            self.frame = frame
            try:
                self.frame.SetIcon(self.icon)
            except:
                pass

            panel = wx.wxPanel(frame, -1)
            self.bgcolor = panel.GetBackgroundColour()

            def StaticText(text, font=self.FONT - 1, underline=False,
                           color=None, panel=panel):
                x = wx.wxStaticText(panel, -1, text, style=wx.wxALIGN_LEFT)
                x.SetFont(wx.wxFont(font, wx.wxDEFAULT, wx.wxNORMAL,
                                    wx.wxNORMAL, underline))
                if color is not None:
                    x.SetForegroundColour(color)
                return x

            colSizer = wx.wxFlexGridSizer(cols=1, vgap=3)

            border = wx.wxBoxSizer(wx.wxHORIZONTAL)
            border.Add(colSizer, 1, wx.wxEXPAND | wx.wxALL, 4)
            panel.SetSizer(border)
            panel.SetAutoLayout(True)

            topboxsizer = wx.wxFlexGridSizer(cols=3, vgap=0)
            topboxsizer.AddGrowableCol(0)

            fnsizer = wx.wxFlexGridSizer(cols=1, vgap=0)
            fnsizer.AddGrowableCol(0)
            fnsizer.AddGrowableRow(1)

            fileNameText = StaticText('', self.FONT + 4)
            fnsizer.Add(fileNameText, 1, wx.wxALIGN_BOTTOM | wx.wxEXPAND)
            self.fileNameText = fileNameText

            fnsizer2 = wx.wxFlexGridSizer(cols=8, vgap=0)
            fnsizer2.AddGrowableCol(0)

            fileSizeText = StaticText('')
            fnsizer2.Add(fileSizeText, 1, wx.wxALIGN_BOTTOM | wx.wxEXPAND)
            self.fileSizeText = fileSizeText

            fileDetails = StaticText('Details', self.FONT, True, 'Blue')
            fnsizer2.Add(fileDetails, 0, wx.wxALIGN_BOTTOM)

            fnsizer2.Add(StaticText('  '))

            advText = StaticText('Advanced', self.FONT, True, 'Blue')
            fnsizer2.Add(advText, 0, wx.wxALIGN_BOTTOM)
            fnsizer2.Add(StaticText('  '))

            prefsText = StaticText('Prefs', self.FONT, True, 'Blue')
            fnsizer2.Add(prefsText, 0, wx.wxALIGN_BOTTOM)
            fnsizer2.Add(StaticText('  '))

            aboutText = StaticText('About', self.FONT, True, 'Blue')
            fnsizer2.Add(aboutText, 0, wx.wxALIGN_BOTTOM)

            fnsizer2.Add(StaticText('  '))
            fnsizer.Add(fnsizer2, 0, wx.wxEXPAND)
            topboxsizer.Add(fnsizer, 0, wx.wxEXPAND)
            topboxsizer.Add(StaticText('  '))

            self.statusIcon = wx.wxEmptyBitmap(32, 32)
            statidata = wx.wxMemoryDC()
            statidata.SelectObject(self.statusIcon)
            statidata.SetPen(wx.wxTRANSPARENT_PEN)
            statidata.SetBrush(wx.wxBrush(self.bgcolor, wx.wxSOLID))
            statidata.DrawRectangle(0, 0, 32, 32)
            self.statusIconPtr = wx.wxStaticBitmap(panel, -1, self.statusIcon)
            topboxsizer.Add(self.statusIconPtr)

            self.fnsizer = fnsizer
            self.fnsizer2 = fnsizer2
            self.topboxsizer = topboxsizer
            colSizer.Add(topboxsizer, 0, wx.wxEXPAND)

            self.gauge = wx.wxGauge(panel, -1, range=1000,
                                    style=wx.wxGA_SMOOTH)
            colSizer.Add(self.gauge, 0, wx.wxEXPAND)

            timeSizer = wx.wxFlexGridSizer(cols=2)
            timeSizer.Add(StaticText('Time elapsed / estimated : '))
            self.timeText = StaticText(self.activity + ' ' * 20)
            timeSizer.Add(self.timeText)
            timeSizer.AddGrowableCol(1)
            colSizer.Add(timeSizer)

            destSizer = wx.wxFlexGridSizer(cols=2, hgap=8)
            self.fileDestLabel = StaticText('Download to:')
            destSizer.Add(self.fileDestLabel)
            self.fileDestText = StaticText('')
            destSizer.Add(self.fileDestText, flag=wx.wxEXPAND)
            destSizer.AddGrowableCol(1)
            colSizer.Add(destSizer, flag=wx.wxEXPAND)
            self.destSizer = destSizer

            statSizer = wx.wxFlexGridSizer(cols=3, hgap=8)

            self.ratesSizer = wx.wxFlexGridSizer(cols=2)
            self.infoSizer = wx.wxFlexGridSizer(cols=2)

            self.ratesSizer.Add(StaticText('   Download rate: '))
            self.downRateText = StaticText('0 kB/s       ')
            self.ratesSizer.Add(self.downRateText, flag=wx.wxEXPAND)

            self.downTextLabel = StaticText('Downloaded: ')
            self.infoSizer.Add(self.downTextLabel)
            self.downText = StaticText('0.00 MiB        ')
            self.infoSizer.Add(self.downText, flag=wx.wxEXPAND)

            self.ratesSizer.Add(StaticText('   Upload rate: '))
            self.upRateText = StaticText('0 kB/s       ')
            self.ratesSizer.Add(self.upRateText, flag=wx.wxEXPAND)

            self.upTextLabel = StaticText('Uploaded: ')
            self.infoSizer.Add(self.upTextLabel)
            self.upText = StaticText('0.00 MiB        ')
            self.infoSizer.Add(self.upText, flag=wx.wxEXPAND)

            shareSizer = wx.wxFlexGridSizer(cols=2, hgap=8)
            shareSizer.Add(StaticText('Share rating:'))
            self.shareRatingText = StaticText('')
            shareSizer.AddGrowableCol(1)
            shareSizer.Add(self.shareRatingText, flag=wx.wxEXPAND)

            statSizer.Add(self.ratesSizer)
            statSizer.Add(self.infoSizer)
            statSizer.Add(shareSizer, flag=wx.wxALIGN_CENTER_VERTICAL)
            colSizer.Add(statSizer)

            torrentSizer = wx.wxFlexGridSizer(cols=1)
            self.peerStatusText = StaticText('')
            torrentSizer.Add(self.peerStatusText, 0, wx.wxEXPAND)
            self.seedStatusText = StaticText('')
            torrentSizer.Add(self.seedStatusText, 0, wx.wxEXPAND)
            torrentSizer.AddGrowableCol(0)
            colSizer.Add(torrentSizer, 0, wx.wxEXPAND)
            self.torrentSizer = torrentSizer

            self.errorTextSizer = wx.wxFlexGridSizer(cols=1)
            self.errorText = StaticText('', self.FONT, False, 'Red')
            self.errorTextSizer.Add(self.errorText, 0, wx.wxEXPAND)
            colSizer.Add(self.errorTextSizer, 0, wx.wxEXPAND)

            cancelSizer = wx.wxGridSizer(cols=2, hgap=40)
            self.pauseButton = wx.wxButton(panel, -1, 'Pause')
            cancelSizer.Add(self.pauseButton, 0, wx.wxALIGN_CENTER)

            self.cancelButton = wx.wxButton(panel, -1, 'Cancel')
            cancelSizer.Add(self.cancelButton, 0, wx.wxALIGN_CENTER)
            colSizer.Add(cancelSizer, 0, wx.wxALIGN_CENTER)

            # Setting options

            slideSizer = wx.wxFlexGridSizer(cols=7, hgap=0, vgap=5)

            # dropdown

            self.connChoiceLabel = StaticText('Settings for ')
            slideSizer.Add(self.connChoiceLabel, 0,
                           wx.wxALIGN_LEFT | wx.wxALIGN_CENTER_VERTICAL)
            self.connChoice = wx.wxChoice(panel, -1, (-1, -1),
                                          (self.FONT * 12, -1),
                                          choices=connChoiceList)
            self.connChoice.SetFont(self.default_font)
            self.connChoice.SetSelection(0)
            slideSizer.Add(self.connChoice, 0, wx.wxALIGN_CENTER)
            self.rateSpinnerLabel = StaticText(' Upload rate (kB/s) ')
            slideSizer.Add(self.rateSpinnerLabel, 0,
                           wx.wxALIGN_RIGHT | wx.wxALIGN_CENTER_VERTICAL)

            # max upload rate

            self.rateSpinner = wx.wxSpinCtrl(panel, -1, "", (-1, -1), (50, -1))
            self.rateSpinner.SetFont(self.default_font)
            self.rateSpinner.SetRange(0, 5000)
            self.rateSpinner.SetValue(0)
            slideSizer.Add(self.rateSpinner, 0,
                           wx.wxALIGN_CENTER | wx.wxALIGN_CENTER_VERTICAL)

            self.rateLowerText = StaticText('%7d' % 0)
            self.rateUpperText = StaticText('%5d' % 5000)
            self.rateslider = wx.wxSlider(panel, -1, 0, 0, 5000, (-1, -1),
                                          (80, -1))

            slideSizer.Add(self.rateLowerText, 0,
                           wx.wxALIGN_RIGHT | wx.wxALIGN_CENTER_VERTICAL)
            slideSizer.Add(self.rateslider, 0,
                           wx.wxALIGN_CENTER | wx.wxALIGN_CENTER_VERTICAL)
            slideSizer.Add(self.rateUpperText, 0,
                           wx.wxALIGN_LEFT | wx.wxALIGN_CENTER_VERTICAL)

            slideSizer.Add(StaticText(''), 0, wx.wxALIGN_LEFT)

            self.bgallocText = StaticText('', self.FONT + 2, False, 'Red')
            slideSizer.Add(self.bgallocText, 0, wx.wxALIGN_LEFT)

            # max uploads

            self.connSpinnerLabel = StaticText(' Max uploads ')
            slideSizer.Add(self.connSpinnerLabel, 0,
                           wx.wxALIGN_RIGHT | wx.wxALIGN_CENTER_VERTICAL)
            self.connSpinner = wx.wxSpinCtrl(panel, -1, "", (-1, -1), (50, -1))
            self.connSpinner.SetFont(self.default_font)
            self.connSpinner.SetRange(4, 100)
            self.connSpinner.SetValue(4)
            slideSizer.Add(self.connSpinner, 0,
                           wx.wxALIGN_CENTER | wx.wxALIGN_CENTER_VERTICAL)

            self.connLowerText = StaticText('%7d' % 4)
            self.connUpperText = StaticText('%5d' % 100)
            self.connslider = wx.wxSlider(panel, -1, 4, 4, 100, (-1, -1),
                                          (80, -1))

            slideSizer.Add(self.connLowerText, 0,
                           wx.wxALIGN_RIGHT | wx.wxALIGN_CENTER_VERTICAL)
            slideSizer.Add(self.connslider, 0,
                           wx.wxALIGN_CENTER | wx.wxALIGN_CENTER_VERTICAL)
            slideSizer.Add(self.connUpperText, 0,
                           wx.wxALIGN_LEFT | wx.wxALIGN_CENTER_VERTICAL)

            colSizer.Add(slideSizer, 1,
                         wx.wxALL | wx.wxALIGN_CENTER | wx.wxEXPAND, 0)

            self.unlimitedLabel = StaticText('0 kB/s means unlimited. Tip: '
                                             'your download rate is '
                                             'proportional to your upload '
                                             'rate', self.FONT - 2)
            colSizer.Add(self.unlimitedLabel, 0, wx.wxALIGN_CENTER)

            self.priorityIDs = [wx.wxNewId() for i in xrange(4)]
            self.prioritycolors = [wx.wxColour(160, 160, 160),
                                   wx.wxColour(255, 64, 0),
                                   wx.wxColour(0, 0, 0),
                                   wx.wxColour(64, 64, 255)]

            wx.EVT_LEFT_DOWN(aboutText, self.about)
            wx.EVT_LEFT_DOWN(fileDetails, self.details)
            wx.EVT_LEFT_DOWN(self.statusIconPtr, self.statusIconHelp)
            wx.EVT_LEFT_DOWN(advText, self.advanced)
            wx.EVT_LEFT_DOWN(prefsText, self.openConfigMenu)
            wx.EVT_CLOSE(frame, self.done)
            wx.EVT_BUTTON(frame, self.pauseButton.GetId(), self.pause)
            wx.EVT_BUTTON(frame, self.cancelButton.GetId(), self.done)
            EVT_INVOKE(frame, self.onInvoke)
            wx.EVT_SCROLL(self.rateslider, self.onRateScroll)
            wx.EVT_SCROLL(self.connslider, self.onConnScroll)
            wx.EVT_CHOICE(self.connChoice, -1, self.onConnChoice)
            wx.EVT_SPINCTRL(self.connSpinner, -1, self.onConnSpinner)
            wx.EVT_SPINCTRL(self.rateSpinner, -1, self.onRateSpinner)
            if (sys.platform == 'win32'):
                self.frame.tbicon = wx.wxTaskBarIcon()
                wx.EVT_ICONIZE(self.frame, self.onIconify)
                wx.EVT_TASKBAR_LEFT_DCLICK(self.frame.tbicon,
                                           self.onTaskBarActivate)
                wx.EVT_TASKBAR_RIGHT_UP(self.frame.tbicon, self.onTaskBarMenu)
                wx.EVT_MENU(self.frame.tbicon, self.TBMENU_RESTORE,
                            self.onTaskBarActivate)
                wx.EVT_MENU(self.frame.tbicon, self.TBMENU_CLOSE, self.done)
            colSizer.AddGrowableCol(0)
            colSizer.AddGrowableRow(6)
            self.frame.Show()
            border.Fit(panel)
            self.frame.Fit()
            self.panel = panel
            self.border = border
            self.addwidth = aboutText.GetBestSize().GetWidth() + \
                fileDetails.GetBestSize().GetWidth() + (self.FONT * 16)
            self.fnsizer = fnsizer
            self.colSizer = colSizer
            minsize = self.colSizer.GetSize()
            minsize.SetWidth(minsize.GetWidth())
            minsize.SetHeight(minsize.GetHeight())
            self.colSizer.SetMinSize(minsize)
            self.colSizer.Fit(self.frame)
            colSizer.Fit(frame)
        except:
            self.exception()

    if sys.platform == 'win32':     # windows-only optimization
        def onInvoke(self, event):
            while self.invokeLaterList:
                func, args, kwargs = self.invokeLaterList[0]
                if self.uiflag.isSet():
                    return
                try:
                    apply(func, args, kwargs)
                except:
                    self.exception()
                del self.invokeLaterList[0]

        def invokeLater(self, func, args=[], kwargs={}):
            if not self.uiflag.isSet():
                self.invokeLaterList.append((func, args, kwargs))
                if len(self.invokeLaterList) == 1:
                    wx.wxPostEvent(self.frame, self.invokeLaterEvent)
    else:
        def onInvoke(self, event):
            if not self.uiflag.isSet():
                try:
                    apply(event.func, event.args, event.kwargs)
                except:
                    self.exception()

        def invokeLater(self, func, args=[], kwargs={}):
            if not self.uiflag.isSet():
                wx.wxPostEvent(self.frame, InvokeEvent(func, args, kwargs))

    def getStatusIcon(self, name, bitmap=False):
        if name in self.statusIcons:
            i = self.statusIcons[name]
            if isinstance(i, wx.wxIcon) and not bitmap:
                return i
        if bitmap:
            i = wx.wxBitmap(self.statusIconFiles[name], wx.wxBITMAP_TYPE_ICO)
        else:
            i = wx.wxIcon(self.statusIconFiles[name], wx.wxBITMAP_TYPE_ICO)
        self.statusIcons[name] = i
        return i

    def setStatusIcon(self, name):
        if name == self.statusIconValue:
            return
        self.statusIconValue = name
        statidata = wx.wxMemoryDC()
        statidata.SelectObject(self.statusIcon)
        statidata.BeginDrawing()
        try:
            statidata.DrawIcon(self.getStatusIcon(name), 0, 0)
        except:
            statidata.DrawBitmap(self.getStatusIcon(name, True), 0, 0, True)
        statidata.EndDrawing()
        statidata.SelectObject(wx.wxNullBitmap)
        self.statusIconPtr.Refresh()

    def createStatusIcon(self, name):
        iconbuffer = wx.wxEmptyBitmap(32, 32)
        bbdata = wx.wxMemoryDC()
        bbdata.SelectObject(iconbuffer)
        bbdata.SetPen(wx.wxTRANSPARENT_PEN)
        bbdata.SetBrush(wx.wxBrush(self.bgcolor, wx.wxSOLID))
        bbdata.DrawRectangle(0, 0, 32, 32)
        try:
            bbdata.DrawIcon(self.getStatusIcon(name), 0, 0)
        except:
            bbdata.DrawBitmap(self.getStatusIcon(name, True), 0, 0, True)
        return iconbuffer

    def setgaugemode(self, selection):
        if selection is None:
            selection = self.gaugemode
        elif selection == self.gaugemode:
            return
        else:
            self.gaugemode = selection
        if selection < 0:
            self.gauge.SetForegroundColour(self.configfile.getcheckingcolor())
            self.gauge.SetBackgroundColour(
                wx.wxSystemSettings_GetColour(wx.wxSYS_COLOUR_MENU))
        elif selection == 0:
            self.gauge.SetForegroundColour(self.configfile.getdownloadcolor())
            self.gauge.SetBackgroundColour(
                wx.wxSystemSettings_GetColour(wx.wxSYS_COLOUR_MENU))
        else:
            self.gauge.SetForegroundColour(self.configfile.getseedingcolor())
            self.gauge.SetBackgroundColour(self.configfile.getdownloadcolor())

    def onIconify(self, evt):
        try:
            if self.configfileargs['win32_taskbar_icon']:
                if self.fin:
                    self.frame.tbicon.SetIcon(self.finicon, "BitTorrent")
                else:
                    self.frame.tbicon.SetIcon(self.icon, "BitTorrent")
                self.frame.Hide()
                self.taskbaricon = True
            else:
                return
        except:
            self.exception()

    def onTaskBarActivate(self, evt):
        try:
            if self.frame.IsIconized():
                self.frame.Iconize(False)
            if not self.frame.IsShown():
                self.frame.Show(True)
                self.frame.Raise()
            self.frame.tbicon.RemoveIcon()
            self.taskbaricon = False
        except wx.wxPyDeadObjectError:
            pass
        except:
            self.exception()

    TBMENU_RESTORE = 1000
    TBMENU_CLOSE = 1001

    def onTaskBarMenu(self, evt):
        menu = wx.wxMenu()
        menu.Append(self.TBMENU_RESTORE, "Restore BitTorrent")
        menu.Append(self.TBMENU_CLOSE,   "Close")
        self.frame.tbicon.PopupMenu(menu)
        menu.Destroy()

    def _try_get_config(self):
        if self.config is None:
            try:
                self.config = self.dow.getConfig()
            except:
                pass
        return self.config is not None

    def onRateScroll(self, event):
        try:
            if self.autorate:
                return
            if not self._try_get_config():
                return
            if (self.scrollock == 0):
                self.scrollock = 1
                self.updateSpinnerFlag = 1
                self.dow.setUploadRate(self.rateslider.GetValue() *
                                       connChoices[
                                           self.connChoice.GetSelection()
                                       ]['rate'].get('div', 1))
                self.scrollock = 0
        except:
            self.exception()

    def onConnScroll(self, event):
        try:
            if self.autorate:
                return
            if not self._try_get_config():
                return
            self.connSpinner.SetValue(self.connslider.GetValue())
            self.dow.setConns(self.connslider.GetValue())
        except:
            self.exception()

    def onRateSpinner(self, event=None):
        try:
            if self.autorate:
                return
            if not self._try_get_config():
                return
            if (self.spinlock == 0):
                self.spinlock = 1
                spinnerValue = self.rateSpinner.GetValue()
                div = connChoices[self.connChoice.GetSelection()]['rate'].get(
                    'div', 1)
                if div > 1:
                    if spinnerValue > (self.config['max_upload_rate']):
                        round_up = div - 1
                    else:
                        round_up = 0
                    newValue = int((spinnerValue + round_up) / div) * div
                    if newValue != spinnerValue:
                        self.rateSpinner.SetValue(newValue)
                else:
                    newValue = spinnerValue
                self.dow.setUploadRate(newValue)
                self.updateSliderFlag = 1
                self.spinlock = 0
        except:
            self.exception()

    def onDownRateSpinner(self, event=None):
        try:
            if not self._try_get_config():
                return
            self.dow.setDownloadRate(self.downrateSpinner.GetValue())
        except:
            self.exception()

    def onConnSpinner(self, event=None):
        try:
            if self.autorate:
                return
            if not self._try_get_config():
                return
            self.connslider.SetValue(self.connSpinner.GetValue())
            self.dow.setConns(self.connslider.GetValue())
        except:
            self.exception()

    def onConnChoice(self, event, cons=None, rate=None):
        try:
            if not self._try_get_config():
                return
            num = self.connChoice.GetSelection()
            choice = connChoices[num]
            if 'super-seed' in choice:  # selecting super-seed is now a toggle
                self.dow.set_super_seed()     # one way change, don't go back
                self.connChoice.SetSelection(self.lastuploadsettings)
                return
            self.lastuploadsettings = num
            self.current_ratesetting = self.connChoice.GetStringSelection()
            if rate is None:
                rate = choice['rate']['def']
            self.rateSpinner.SetRange(choice['rate']['min'],
                                      choice['rate']['max'])
            self.rateSpinner.SetValue(rate)
            self.rateslider.SetRange(
                choice['rate']['min'] / choice['rate'].get('div', 1),
                choice['rate']['max'] / choice['rate'].get('div', 1))
            self.rateslider.SetValue(rate / choice['rate'].get('div', 1))
            self.rateLowerText.SetLabel('  %d' % choice['rate']['min'])
            self.rateUpperText.SetLabel('%d' % choice['rate']['max'])
            if cons is None:
                cons = choice['conn']['def']
            self.connSpinner.SetRange(choice['conn']['min'],
                                      choice['conn']['max'])
            self.connSpinner.SetValue(cons)
            self.connslider.SetRange(choice['conn']['min'],
                                     choice['conn']['max'])
            self.connslider.SetValue(cons)
            self.connLowerText.SetLabel('  %d' % choice['conn']['min'])
            self.connUpperText.SetLabel('%d' % choice['conn']['max'])
            self.onConnScroll(0)
            self.onRateScroll(0)
            self.dow.setInitiate(choice.get('initiate', 40))
            if 'automatic' in choice:
                if not self.autorate:
                    self.autorate = True
                    self.rateSpinner.Enable(False)
                    self.connSpinner.Enable(False)
                    self.dow.setUploadRate(-1)
            else:
                if self.autorate:
                    self.autorate = False
                    self.rateSpinner.Enable(True)
                    self.connSpinner.Enable(True)
                    self.onRateSpinner()
                    self.onConnSpinner()
        except:
            self.exception()

    def about(self, event):
        try:
            if (self.aboutBox is not None):
                try:
                    self.aboutBox.Close()
                except wx.wxPyDeadObjectError:
                    self.aboutBox = None

            self.aboutBox = wx.wxFrame(
                None, -1, 'About BitTorrent', size=(1, 1),
                style=wx.wxDEFAULT_FRAME_STYLE | wx.wxFULL_REPAINT_ON_RESIZE)
            try:
                self.aboutBox.SetIcon(self.icon)
            except:
                pass

            panel = wx.wxPanel(self.aboutBox, -1)

            def StaticText(text, font=self.FONT, underline=False, color=None,
                           panel=panel):
                x = wx.wxStaticText(panel, -1, text, style=wx.wxALIGN_LEFT)
                x.SetFont(wx.wxFont(font, wx.wxDEFAULT, wx.wxNORMAL,
                                    wx.wxNORMAL, underline))
                if color is not None:
                    x.SetForegroundColour(color)
                return x

            colSizer = wx.wxFlexGridSizer(cols=1, vgap=3)

            titleSizer = wx.wxBoxSizer(wx.wxHORIZONTAL)
            aboutTitle = StaticText('BitTorrent {}  '.format(version),
                                    self.FONT + 4)
            titleSizer.Add(aboutTitle)
            linkDonate = StaticText('Donate to Bram', self.FONT, True, 'Blue')
            titleSizer.Add(linkDonate, 1, wx.wxALIGN_BOTTOM & wx.wxEXPAND)
            colSizer.Add(titleSizer, 0, wx.wxEXPAND)

            colSizer.Add(StaticText('created by Bram Cohen, Copyright '
                         '2001-2003,'))
            colSizer.Add(StaticText('experimental version maintained by John'
                         ' Hoffman 2003'))
            colSizer.Add(StaticText('modified from experimental version by '
                         'Eike Frost 2003'))
            credits = StaticText('full credits\n', self.FONT, True, 'Blue')
            colSizer.Add(credits)

            si = '\n'.join(('exact Version String: ' + version,
                           'Python version: ' + sys.version,
                           'wxPython version: ' + wx.wxVERSION_STRING))
            colSizer.Add(StaticText(si))

            babble1 = StaticText(
                'This is an experimental, unofficial build of BitTorrent.\n' +
                'It is Free Software under an MIT-Style license.')
            babble2 = StaticText('BitTorrent Homepage (link)', self.FONT, True,
                                 'Blue')
            babble3 = StaticText("TheSHAD0W's Client Homepage (link)",
                                 self.FONT, True, 'Blue')
            babble4 = StaticText("Eike Frost's Client Homepage (link)",
                                 self.FONT, True, 'Blue')
            babble6 = StaticText('License Terms (link)', self.FONT, True,
                                 'Blue')
            colSizer.Add(babble1)
            colSizer.Add(babble2)
            colSizer.Add(babble3)
            colSizer.Add(babble4)
            colSizer.Add(babble6)

            okButton = wx.wxButton(panel, -1, 'Ok')
            colSizer.Add(okButton, 0, wx.wxALIGN_RIGHT)
            colSizer.AddGrowableCol(0)

            border = wx.wxBoxSizer(wx.wxHORIZONTAL)
            border.Add(colSizer, 1, wx.wxEXPAND | wx.wxALL, 4)
            panel.SetSizer(border)
            panel.SetAutoLayout(True)

            def donatelink(self):
                threading.Thread(
                    target=open_new('https://www.paypal.com/cgi-bin/webscr?'
                                    'cmd=_xclick&business=bram@bitconjurer.'
                                    'org&item_name=BitTorrent&amount=5.00&'
                                    'submit=donate')).start()
            wx.EVT_LEFT_DOWN(linkDonate, donatelink)

            def aboutlink(self):
                threading.Thread(
                    target=open_new('http://bitconjurer.org/BitTorrent/')
                ).start()
            wx.EVT_LEFT_DOWN(babble2, aboutlink)

            def shadlink(self):
                threading.Thread(
                    target=open_new('http://www.bittornado.com/')).start()
            wx.EVT_LEFT_DOWN(babble3, shadlink)

            def explink(self):
                threading.Thread(
                    target=open_new('http://ei.kefro.st/projects/btclient/')
                ).start()
            wx.EVT_LEFT_DOWN(babble4, explink)

            def licenselink(self):
                threading.Thread(
                    target=open_new('http://ei.kefro.st/projects/btclient/'
                                    'LICENSE.TXT')).start()
            wx.EVT_LEFT_DOWN(babble6, licenselink)
            wx.EVT_LEFT_DOWN(credits, self.credits)

            def closeAbout(e, self=self):
                if self.aboutBox:
                    self.aboutBox.Close()
            wx.EVT_BUTTON(self.aboutBox, okButton.GetId(), closeAbout)

            def kill(e, self=self):
                try:
                    self.aboutBox.RemoveIcon()
                except:
                    pass
                self.aboutBox.Destroy()
                self.aboutBox = None
            wx.EVT_CLOSE(self.aboutBox, kill)

            self.aboutBox.Show()
            border.Fit(panel)
            self.aboutBox.Fit()
        except:
            self.exception()

    def details(self, event):
        try:
            if not self.dow or not self.filename:
                return
            metainfo = self.dow.getResponse()
            if metainfo is None:
                return
            announce = metainfo.get('announce')
            announce_list = metainfo.get('announce-list')

            info = metainfo['info']
            info_hash = self.dow.infohash
            piece_length = info['piece length']
            fileselector = self.dow.fileselector

            if (self.detailBox is not None):
                try:
                    self.detailBox.Close()
                except wx.wxPyDeadObjectError:
                    self.detailBox = None

            self.detailBox = wx.wxFrame(
                None, -1, 'Torrent Details ', size=wx.wxSize(405, 230),
                style=wx.wxDEFAULT_FRAME_STYLE | wx.wxFULL_REPAINT_ON_RESIZE)
            try:
                self.detailBox.SetIcon(self.icon)
            except:
                pass

            panel = wx.wxPanel(self.detailBox, -1, size=wx.wxSize(400, 220))

            def StaticText(text, font=self.FONT - 1, underline=False,
                           color=None, panel=panel):
                x = wx.wxStaticText(panel, -1, text,
                                    style=wx.wxALIGN_CENTER_VERTICAL)
                x.SetFont(wx.wxFont(font, wx.wxDEFAULT, wx.wxNORMAL,
                                    wx.wxNORMAL, underline))
                if color is not None:
                    x.SetForegroundColour(color)
                return x

            colSizer = wx.wxFlexGridSizer(cols=1, vgap=3)
            colSizer.AddGrowableCol(0)

            titleSizer = wx.wxBoxSizer(wx.wxHORIZONTAL)
            aboutTitle = StaticText('Details about ' + self.filename,
                                    self.FONT + 4)

            titleSizer.Add(aboutTitle)
            colSizer.Add(titleSizer)

            detailSizer = wx.wxFlexGridSizer(cols=2, vgap=6)

            if 'length' in info:
                fileListID = None
                detailSizer.Add(StaticText('file name :'))
                detailSizer.Add(StaticText(info['name']))
                if 'md5sum' in info:
                    detailSizer.Add(StaticText('MD5 hash :'))
                    detailSizer.Add(StaticText(info['md5sum']))
                file_length = info['length']
                name = "file size"
            else:
                detail1Sizer = wx.wxFlexGridSizer(cols=1, vgap=6)
                detail1Sizer.Add(StaticText('directory name : {}'.format(
                    info['name'])))
                colSizer.Add(detail1Sizer)
                bgallocButton = wx.wxBitmapButton(
                    panel, -1, self.allocbuttonBitmap, size=(52, 20))

                def bgalloc(self, frame=self):
                    if frame.dow.storagewrapper is not None:
                        frame.dow.storagewrapper.bgalloc()
                wx.EVT_BUTTON(self.detailBox, bgallocButton.GetId(), bgalloc)

                bgallocbuttonSizer = wx.wxFlexGridSizer(cols=4, hgap=4, vgap=0)
                bgallocbuttonSizer.Add(
                    StaticText('(right-click to set priority)', self.FONT - 1),
                    0, wx.wxALIGN_BOTTOM)
                bgallocbuttonSizer.Add(StaticText('(finish allocation)'), -1,
                                       wx.wxALIGN_CENTER_VERTICAL)
                bgallocbuttonSizer.Add(bgallocButton, -1, wx.wxALIGN_CENTER)
                bgallocbuttonSizer.AddGrowableCol(0)
                colSizer.Add(bgallocbuttonSizer, -1, wx.wxEXPAND)

                file_length = 0

                fileListID = wx.wxNewId()
                fileList = wx.wxListCtrl(panel, fileListID, wx.wxPoint(-1, -1),
                                         (325, 100), wx.wxLC_REPORT)
                self.fileList = fileList
                fileList.SetImageList(self.filestatusIcons,
                                      wx.wxIMAGE_LIST_SMALL)

                fileList.SetAutoLayout(True)
                fileList.InsertColumn(0, "file")
                fileList.InsertColumn(1, "", format=wx.wxLIST_FORMAT_RIGHT,
                                      width=55)
                fileList.InsertColumn(2, "")

                for i in xrange(len(info['files'])):
                    x = wx.wxListItem()
                    fileList.InsertItem(x)

                x = 0
                for file in info['files']:
                    path = ' '
                    for item in file['path']:
                        if (path != ''):
                            path = path + "/"
                        path = path + item
                    path += ' (' + str(file['length']) + ')'
                    fileList.SetStringItem(x, 0, path)
                    if 'md5sum' in file:
                        fileList.SetStringItem(x, 2, '    [{:s}]'.format(
                            file['md5sum']))
                    if fileselector:
                        p = fileselector[x]
                        item = self.fileList.GetItem(x)
                        item.SetTextColour(self.prioritycolors[p + 1])
                        fileList.SetItem(item)
                    x += 1
                    file_length += file['length']
                fileList.SetColumnWidth(0, wx.wxLIST_AUTOSIZE)
                fileList.SetColumnWidth(2, wx.wxLIST_AUTOSIZE)

                name = 'archive size'
                colSizer.Add(fileList, 1, wx.wxEXPAND)
                colSizer.AddGrowableRow(3)

            detailSizer.Add(StaticText('info_hash :'), 0,
                            wx.wxALIGN_CENTER_VERTICAL)
            detailSizer.Add(wx.wxTextCtrl(panel, -1, hexlify(info_hash),
                            size=(325, -1), style=wx.wxTE_READONLY))
            num_pieces = int((file_length + piece_length - 1) / piece_length)
            detailSizer.Add(StaticText(name + ' : '))
            detailSizer.Add(StaticText('{} ({} bytes)'.format(
                size_format(file_length), comma_format(file_length))))
            detailSizer.Add(StaticText('pieces : '))
            if num_pieces > 1:
                detailSizer.Add(StaticText('{:i} ({} bytes each)'.format(
                    num_pieces, comma_format(piece_length))))
            else:
                detailSizer.Add(StaticText('1'))

            if announce_list is None:
                detailSizer.Add(StaticText('announce url : '), 0,
                                wx.wxALIGN_CENTER_VERTICAL)
                detailSizer.Add(wx.wxTextCtrl(panel, -1, announce,
                                size=(325, -1), style=wx.wxTE_READONLY))
            else:
                detailSizer.Add(StaticText(''))
                trackerList = wx.wxListCtrl(panel, -1, wx.wxPoint(-1, -1),
                                            (325, 75), wx.wxLC_REPORT)
                trackerList.SetAutoLayout(True)
                trackerList.InsertColumn(0, "")
                trackerList.InsertColumn(1, "announce urls")

                for tier in range(len(announce_list)):
                    for t in range(len(announce_list[tier])):
                        i = wx.wxListItem()
                        trackerList.InsertItem(i)
                if announce is not None:
                    for l in [1, 2]:
                        i = wx.wxListItem()
                        trackerList.InsertItem(i)

                x = 0
                for tier in range(len(announce_list)):
                    for t in range(len(announce_list[tier])):
                        if t == 0:
                            trackerList.SetStringItem(x, 0, 'tier {}:'.format(
                                tier))
                        trackerList.SetStringItem(x, 1, announce_list[tier][t])
                        x += 1
                if announce is not None:
                    trackerList.SetStringItem(x + 1, 0, 'single:')
                    trackerList.SetStringItem(x + 1, 1, announce)
                trackerList.SetColumnWidth(0, wx.wxLIST_AUTOSIZE)
                trackerList.SetColumnWidth(1, wx.wxLIST_AUTOSIZE)
                detailSizer.Add(trackerList)

            if announce is None and announce_list is not None:
                announce = announce_list[0][0]
            if announce is not None:
                detailSizer.Add(StaticText('likely tracker :'))
                p = re.compile('(.*/)[^/]+')
                turl = p.sub(r'\1', announce)
                trackerUrl = StaticText(turl, self.FONT, True, 'Blue')
                detailSizer.Add(trackerUrl)
            if 'comment' in metainfo:
                detailSizer.Add(StaticText('comment :'))
                detailSizer.Add(StaticText(metainfo['comment']))
            if 'creation date' in metainfo:
                detailSizer.Add(StaticText('creation date :'))
                try:
                    detailSizer.Add(StaticText(time.strftime(
                        '%x %X', time.localtime(metainfo['creation date']))))
                except:
                    try:
                        detailSizer.Add(StaticText(metainfo['creation date']))
                    except:
                        detailSizer.Add(StaticText('<cannot read date>'))

            detailSizer.AddGrowableCol(1)
            colSizer.Add(detailSizer, 1, wx.wxEXPAND)

            okButton = wx.wxButton(panel, -1, 'Ok')
            colSizer.Add(okButton, 0, wx.wxALIGN_RIGHT)
            colSizer.AddGrowableCol(0)

            if not self.configfileargs['gui_stretchwindow']:
                aboutTitle.SetSize((400, -1))
            else:
                panel.SetAutoLayout(True)

            border = wx.wxBoxSizer(wx.wxHORIZONTAL)
            border.Add(colSizer, 1, wx.wxEXPAND | wx.wxALL, 4)
            panel.SetSizer(border)
            panel.SetAutoLayout(True)

            if fileselector and fileListID:
                def onRightClick(evt, self=self):
                    s = []
                    i = -1
                    while True:
                        i = self.fileList.GetNextItem(
                            i, state=wx.wxLIST_STATE_SELECTED)
                        if i == -1:
                            break
                        s.append(i)
                    if not s:   # just in case
                        return
                    oldstate = self.dow.fileselector[s[0]]
                    kind = wx.wxITEM_RADIO
                    for i in s[1:]:
                        if self.dow.fileselector[i] != oldstate:
                            oldstate = None
                            kind = wx.wxITEM_NORMAL
                            break
                    menu = wx.wxMenu()
                    menu.Append(self.priorityIDs[1], "download first",
                                kind=kind)
                    menu.Append(self.priorityIDs[2], "download normally",
                                kind=kind)
                    menu.Append(self.priorityIDs[3], "download later",
                                kind=kind)
                    menu.Append(
                        self.priorityIDs[0], "download never (deletes)",
                        kind=kind)
                    if oldstate is not None:
                        menu.Check(self.priorityIDs[oldstate + 1], True)

                    def onSelection(evt, self=self, s=s):
                        p = evt.GetId()
                        priorities = self.dow.fileselector.get_priorities()
                        for i in xrange(len(self.priorityIDs)):
                            if p == self.priorityIDs[i]:
                                for ss in s:
                                    priorities[ss] = i - 1
                                    item = self.fileList.GetItem(ss)
                                    item.SetTextColour(self.prioritycolors[i])
                                    self.fileList.SetItem(item)
                                self.dow.fileselector.set_priorities(
                                    priorities)
                                self.fileList.Refresh()
                                self.refresh_details = True
                                break

                    for id in self.priorityIDs:
                        wx.EVT_MENU(self.detailBox, id, onSelection)

                    self.detailBox.PopupMenu(menu, evt.GetPoint())

                wx.EVT_LIST_ITEM_RIGHT_CLICK(self.detailBox, fileListID,
                                             onRightClick)

            def closeDetail(evt, self=self):
                if self.detailBox:
                    self.detailBox.Close()
            wx.EVT_BUTTON(self.detailBox, okButton.GetId(), closeDetail)

            def kill(evt, self=self):
                try:
                    self.detailBox.RemoveIcon()
                except:
                    pass
                self.detailBox.Destroy()
                self.detailBox = None
                self.fileList = None
                self.dow.filedatflag.clear()
            wx.EVT_CLOSE(self.detailBox, kill)

            def trackerurl(self, turl=turl):
                try:
                    threading.Thread(target=open_new(turl)).start()
                except:
                    pass
            wx.EVT_LEFT_DOWN(trackerUrl, trackerurl)

            self.detailBox.Show()
            border.Fit(panel)
            self.detailBox.Fit()

            self.refresh_details = True
            self.dow.filedatflag.set()
        except:
            self.exception()

    def credits(self, event):
        try:
            if (self.creditsBox is not None):
                try:
                    self.creditsBox.Close()
                except wx.wxPyDeadObjectError:
                    self.creditsBox = None

            self.creditsBox = wx.wxFrame(
                None, -1, 'Credits', size=(1, 1),
                style=wx.wxDEFAULT_FRAME_STYLE | wx.wxFULL_REPAINT_ON_RESIZE)
            try:
                self.creditsBox.SetIcon(self.icon)
            except:
                pass

            panel = wx.wxPanel(self.creditsBox, -1)

            def StaticText(text, font=self.FONT, underline=False, color=None,
                           panel=panel):
                x = wx.wxStaticText(panel, -1, text, style=wx.wxALIGN_LEFT)
                x.SetFont(wx.wxFont(font, wx.wxDEFAULT, wx.wxNORMAL,
                                    wx.wxNORMAL, underline))
                if color is not None:
                    x.SetForegroundColour(color)
                return x

            colSizer = wx.wxFlexGridSizer(cols=1, vgap=3)

            titleSizer = wx.wxBoxSizer(wx.wxHORIZONTAL)
            aboutTitle = StaticText('Credits', self.FONT + 4)
            titleSizer.Add(aboutTitle)
            colSizer.Add(titleSizer)
            colSizer.Add(StaticText(
                'The following people have all helped with this\nversion of'
                'BitTorrent in some way (in no particular order) -\n'))
            creditSizer = wx.wxFlexGridSizer(cols=3)
            creditSizer.Add(StaticText(
                'Bill Bumgarner\n'
                'David Creswick\n'
                'Andrew Loewenstern\n'
                'Ross Cohen\n'
                'Jeremy Avnet\n'
                'Greg Broiles\n'
                'Barry Cohen\n'
                'Bram Cohen\n'
                'sayke\n'
                'Steve Jenson\n'
                'Myers Carpenter\n'
                'Francis Crick\n'
                'Petru Paler\n'
                'Jeff Darcy\n'
                'John Gilmore\n'
                'Xavier Bassery\n'
                'Pav Lucistnik'))
            creditSizer.Add(StaticText('  '))
            creditSizer.Add(StaticText(
                'Yann Vernier\n'
                'Pat Mahoney\n'
                'Boris Zbarsky\n'
                'Eric Tiedemann\n'
                'Henry "Pi" James\n'
                'Loring Holden\n'
                'Robert Stone\n'
                'Michael Janssen\n'
                'Eike Frost\n'
                'Andrew Todd\n'
                'otaku\n'
                'Edward Keyes\n'
                'John Hoffman\n'
                'Uoti Urpala\n'
                'Jon Wolf\n'
                'Christoph Hohmann\n'
                'Micah Anderson'))
            colSizer.Add(creditSizer, flag=wx.wxALIGN_CENTER_HORIZONTAL)
            okButton = wx.wxButton(panel, -1, 'Ok')
            colSizer.Add(okButton, 0, wx.wxALIGN_RIGHT)
            colSizer.AddGrowableCol(0)

            border = wx.wxBoxSizer(wx.wxHORIZONTAL)
            border.Add(colSizer, 1, wx.wxEXPAND | wx.wxALL, 4)
            panel.SetSizer(border)
            panel.SetAutoLayout(True)

            def closeCredits(e, self=self):
                if self.creditsBox:
                    self.creditsBox.Close()
            wx.EVT_BUTTON(self.creditsBox, okButton.GetId(), closeCredits)

            def kill(e, self=self):
                try:
                    self.creditsBox.RemoveIcon()
                except:
                    pass
                self.creditsBox.Destroy()
                self.creditsBox = None
            wx.EVT_CLOSE(self.creditsBox, kill)

            self.creditsBox.Show()
            border.Fit(panel)
            self.creditsBox.Fit()
        except:
            self.exception()

    def statusIconHelp(self, event):
        try:
            if (self.statusIconHelpBox is not None):
                try:
                    self.statusIconHelpBox.Close()
                except wx.wxPyDeadObjectError:
                    self.statusIconHelpBox = None

            self.statusIconHelpBox = wx.wxFrame(
                None, -1, 'Help with the BitTorrent Status Light', size=(1, 1),
                style=wx.wxDEFAULT_FRAME_STYLE | wx.wxFULL_REPAINT_ON_RESIZE)
            try:
                self.statusIconHelpBox.SetIcon(self.icon)
            except:
                pass

            panel = wx.wxPanel(self.statusIconHelpBox, -1)

            def StaticText(text, font=self.FONT, underline=False, color=None,
                           panel=panel):
                x = wx.wxStaticText(panel, -1, text, style=wx.wxALIGN_LEFT)
                x.SetFont(wx.wxFont(font, wx.wxDEFAULT, wx.wxNORMAL,
                                    wx.wxNORMAL, underline))
                if color is not None:
                    x.SetForegroundColour(color)
                return x

            fullsizer = wx.wxFlexGridSizer(cols=1, vgap=13)
            colsizer = wx.wxFlexGridSizer(cols=2, hgap=13, vgap=13)

            disconnectedicon = self.createStatusIcon('disconnected')
            colsizer.Add(wx.wxStaticBitmap(panel, -1, disconnectedicon))
            colsizer.Add(StaticText(
                'Waiting to connect to the tracker.\n'
                'If the status light stays black for a long time the tracker\n'
                'you are trying to connect to may not be working. Unless you\n'
                'are receiving a message telling you otherwise, please wait,\n'
                'and BitTorrent will automatically try to reconnect for you.'),
                1, wx.wxALIGN_CENTER_VERTICAL)

            noconnectionsicon = self.createStatusIcon('noconnections')
            colsizer.Add(wx.wxStaticBitmap(panel, -1, noconnectionsicon))
            colsizer.Add(StaticText(
                'You have no connections with other clients.\n'
                'Please be patient.  If after several minutes the status\n'
                'light remains red, this torrent may be old and abandoned.'),
                1, wx.wxALIGN_CENTER_VERTICAL)

            noincomingicon = self.createStatusIcon('noincoming')
            colsizer.Add(wx.wxStaticBitmap(panel, -1, noincomingicon))
            colsizer.Add(StaticText(
                'You have not received any incoming connections from others.\n'
                'It may only be because no one has tried.  If you never see\n'
                'the status light turn green, it may indicate your system\n'
                'is behind a firewall or proxy server.  Please look into\n'
                'routing BitTorrent through your firewall in order to '
                'receive\nthe best possible download rate.'), 1,
                wx.wxALIGN_CENTER_VERTICAL)

            nocompletesicon = self.createStatusIcon('nocompletes')
            colsizer.Add(wx.wxStaticBitmap(panel, -1, nocompletesicon))
            colsizer.Add(StaticText(
                'There are no complete copies among the clients you are\n' +
                'connected to.  Don\'t panic, other clients in the torrent\n' +
                "you can't see may have the missing data.\n" +
                'If the status light remains blue, you may have problems\n' +
                'completing your download.'), 1, wx.wxALIGN_CENTER_VERTICAL)

            allgoodicon = self.createStatusIcon('allgood')
            colsizer.Add(wx.wxStaticBitmap(panel, -1, allgoodicon))
            colsizer.Add(StaticText('The torrent is operating properly.'), 1,
                         wx.wxALIGN_CENTER_VERTICAL)

            fullsizer.Add(colsizer, 0, wx.wxALIGN_CENTER)
            colsizer2 = wx.wxFlexGridSizer(cols=1, hgap=13)

            colsizer2.Add(StaticText(
                'Please note that the status light is not omniscient, and that'
                'it may\nbe wrong in many instances.  A torrent with a blue '
                'light may complete\nnormally, and an occasional yellow light '
                "doesn't mean your computer\nhas suddenly become firewalled."),
                1, wx.wxALIGN_CENTER_VERTICAL)

            colspacer = StaticText('  ')
            colsizer2.Add(colspacer)

            okButton = wx.wxButton(panel, -1, 'Ok')
            colsizer2.Add(okButton, 0, wx.wxALIGN_CENTER)
            fullsizer.Add(colsizer2, 0, wx.wxALIGN_CENTER)

            border = wx.wxBoxSizer(wx.wxHORIZONTAL)
            border.Add(fullsizer, 1, wx.wxEXPAND | wx.wxALL, 4)

            panel.SetSizer(border)
            panel.SetAutoLayout(True)

            def closeHelp(self, frame=self):
                frame.statusIconHelpBox.Close()
            wx.EVT_BUTTON(self.statusIconHelpBox, okButton.GetId(), closeHelp)

            self.statusIconHelpBox.Show()
            border.Fit(panel)
            self.statusIconHelpBox.Fit()
        except:
            self.exception()

    def openConfigMenu(self, event):
        try:
            self.configfile.configMenu(self)
        except:
            self.exception()

    def advanced(self, event):
        try:
            if not self.dow or not self.filename:
                return
            if (self.advBox is not None):
                try:
                    self.advBox.Close()
                except wx.wxPyDeadObjectError:
                    self.advBox = None

            self.advBox = wx.wxFrame(
                None, -1, 'BitTorrent Advanced', size=wx.wxSize(200, 200),
                style=wx.wxDEFAULT_FRAME_STYLE | wx.wxFULL_REPAINT_ON_RESIZE)
            try:
                self.advBox.SetIcon(self.icon)
            except:
                pass

            panel = wx.wxPanel(self.advBox, -1, size=wx.wxSize(200, 200))

            def StaticText(text, font=self.FONT - 1, underline=False,
                           color=None, panel=panel):
                x = wx.wxStaticText(panel, -1, text, style=wx.wxALIGN_LEFT)
                x.SetFont(wx.wxFont(font, wx.wxDEFAULT, wx.wxNORMAL,
                                    wx.wxNORMAL, underline))
                if color is not None:
                    x.SetForegroundColour(color)
                return x

            colSizer = wx.wxFlexGridSizer(cols=1, vgap=1)
            colSizer.Add(StaticText('Advanced Info for ' + self.filename,
                         self.FONT + 4))

            try:    # get system font width
                fw = wx.wxSystemSettings_GetFont(
                    wx.wxSYS_DEFAULT_GUI_FONT
                ).GetPointSize() + 1
            except:
                fw = wx.wxSystemSettings_GetFont(
                    wx.wxSYS_SYSTEM_FONT
                ).GetPointSize() + 1

            spewList = wx.wxListCtrl(
                panel, -1, wx.wxPoint(-1, -1), (fw * 66, 350),
                wx.wxLC_REPORT | wx.wxLC_HRULES | wx.wxLC_VRULES)
            self.spewList = spewList
            spewList.SetAutoLayout(True)

            colSizer.Add(spewList, -1, wx.wxEXPAND)

            colSizer.Add(StaticText(''))
            self.storagestats1 = StaticText('')
            self.storagestats2 = StaticText('')
            colSizer.Add(self.storagestats1, -1, wx.wxEXPAND)
            colSizer.Add(self.storagestats2, -1, wx.wxEXPAND)
            spinnerSizer = wx.wxFlexGridSizer(cols=4, vgap=0, hgap=0)
            cstats = '          Listening on '
            if self.connection_stats['interfaces']:
                cstats += ', '.join(self.connection_stats['interfaces']) + \
                          ' on '
            cstats += 'port ' + str(self.connection_stats['port'])
            if self.connection_stats['upnp']:
                cstats += ', UPnP port forwarded'
            spinnerSizer.Add(StaticText(cstats), -1, wx.wxEXPAND)
            spinnerSizer.AddGrowableCol(0)
            spinnerSizer.Add(StaticText('Max download rate (kB/s) '), 0,
                             wx.wxALIGN_CENTER_VERTICAL)
            self.downrateSpinner = wx.wxSpinCtrl(panel, -1, "", (-1, -1)
                                                 (50, -1))
            self.downrateSpinner.SetFont(self.default_font)
            self.downrateSpinner.SetRange(0, 5000)
            self.downrateSpinner.SetValue(self.config['max_download_rate'])
            spinnerSizer.Add(self.downrateSpinner, 0)
            wx.EVT_SPINCTRL(self.downrateSpinner, -1, self.onDownRateSpinner)
            spinnerSizer.Add(StaticText(' (0 = unlimited)  '), 0,
                             wx.wxALIGN_CENTER_VERTICAL)
            colSizer.Add(spinnerSizer, 0, wx.wxEXPAND)

            colSizer.Add(StaticText(''))

            buttonSizer = wx.wxFlexGridSizer(cols=5, hgap=20)

            reannounceButton = wx.wxButton(panel, -1, 'Manual Announce')
            buttonSizer.Add(reannounceButton)

            extannounceButton = wx.wxButton(panel, -1, 'External Announce')
            buttonSizer.Add(extannounceButton)

            bgallocButton = wx.wxButton(panel, -1, 'Finish Allocation')
            buttonSizer.Add(bgallocButton)

            buttonSizer.Add(StaticText(''))

            okButton = wx.wxButton(panel, -1, 'Ok')
            buttonSizer.Add(okButton)

            colSizer.Add(buttonSizer, 0, wx.wxALIGN_CENTER)
            colSizer.AddGrowableCol(0)
            colSizer.AddGrowableRow(1)

            panel.SetSizer(colSizer)
            panel.SetAutoLayout(True)

            spewList.InsertColumn(0, "Optimistic Unchoke",
                                  format=wx.wxLIST_FORMAT_CENTER, width=fw * 2)
            spewList.InsertColumn(1, "Peer ID", width=0)
            spewList.InsertColumn(2, "IP", width=fw * 11)
            spewList.InsertColumn(3, "Local/Remote",
                                  format=wx.wxLIST_FORMAT_CENTER, width=fw * 3)
            spewList.InsertColumn(4, "Up", format=wx.wxLIST_FORMAT_RIGHT,
                                  width=fw * 6)
            spewList.InsertColumn(5, "Interested",
                                  format=wx.wxLIST_FORMAT_CENTER, width=fw * 2)
            spewList.InsertColumn(6, "Choking", format=wx.wxLIST_FORMAT_CENTER,
                                  width=fw * 2)
            spewList.InsertColumn(7, "Down", format=wx.wxLIST_FORMAT_RIGHT,
                                  width=fw * 6)
            spewList.InsertColumn(8, "Interesting",
                                  format=wx.wxLIST_FORMAT_CENTER, width=fw * 2)
            spewList.InsertColumn(9, "Choked", format=wx.wxLIST_FORMAT_CENTER,
                                  width=fw * 2)
            spewList.InsertColumn(10, "Snubbed",
                                  format=wx.wxLIST_FORMAT_CENTER, width=fw * 2)
            spewList.InsertColumn(11, "Downloaded",
                                  format=wx.wxLIST_FORMAT_RIGHT, width=fw * 7)
            spewList.InsertColumn(12, "Uploaded",
                                  format=wx.wxLIST_FORMAT_RIGHT, width=fw * 7)
            spewList.InsertColumn(13, "Completed",
                                  format=wx.wxLIST_FORMAT_RIGHT, width=fw * 6)
            spewList.InsertColumn(14, "Peer Download Speed",
                                  format=wx.wxLIST_FORMAT_RIGHT, width=fw * 6)

            def reannounce(self, frame=self):
                if (clock() - frame.reannouncelast > 60):
                    frame.reannouncelast = clock()
                    frame.dow.reannounce()
            wx.EVT_BUTTON(self.advBox, reannounceButton.GetId(), reannounce)

            self.advextannouncebox = None

            def reannounce_external(self, frame=self):
                if (frame.advextannouncebox is not None):
                    try:
                        frame.advextannouncebox.Close()
                    except wx.wxPyDeadObjectError:
                        frame.advextannouncebox = None

                frame.advextannouncebox = wx.wxFrame(
                    None, -1, 'External Announce', size=(1, 1),
                    style=wx.wxDEFAULT_FRAME_STYLE |
                    wx.wxFULL_REPAINT_ON_RESIZE)
                try:
                    frame.advextannouncebox.SetIcon(frame.icon)
                except:
                    pass

                panel = wx.wxPanel(frame.advextannouncebox, -1)

                fullsizer = wx.wxFlexGridSizer(cols=1, vgap=13)
                msg = wx.wxStaticText(panel, -1, "Enter tracker anounce URL:")
                msg.SetFont(frame.default_font)
                fullsizer.Add(msg)

                frame.advexturl = wx.wxTextCtrl(
                    parent=panel, id=-1, value='', size=(255, 20),
                    style=wx.wxTE_PROCESS_TAB)
                frame.advexturl.SetFont(frame.default_font)
                frame.advexturl.SetValue(frame.lastexternalannounce)
                fullsizer.Add(frame.advexturl)

                buttonSizer = wx.wxFlexGridSizer(cols=2, hgap=10)

                okButton = wx.wxButton(panel, -1, 'OK')
                buttonSizer.Add(okButton)

                cancelButton = wx.wxButton(panel, -1, 'Cancel')
                buttonSizer.Add(cancelButton)

                fullsizer.Add(buttonSizer, 0, wx.wxALIGN_CENTER)

                border = wx.wxBoxSizer(wx.wxHORIZONTAL)
                border.Add(fullsizer, 1, wx.wxEXPAND | wx.wxALL, 4)

                panel.SetSizer(border)
                panel.SetAutoLayout(True)

                def ok(self, frame=frame):
                    special = frame.advexturl.GetValue()
                    if special:
                        frame.lastexternalannounce = special
                        if (clock() - frame.reannouncelast > 60):
                            frame.reannouncelast = clock()
                            frame.dow.reannounce(special)
                    frame.advextannouncebox.Close()
                wx.EVT_BUTTON(frame.advextannouncebox, okButton.GetId(), ok)

                def cancel(self, frame=frame):
                    frame.advextannouncebox.Close()
                wx.EVT_BUTTON(frame.advextannouncebox, cancelButton.GetId(),
                              cancel)

                frame.advextannouncebox.Show()
                fullsizer.Fit(panel)
                frame.advextannouncebox.Fit()

            wx.EVT_BUTTON(self.advBox, extannounceButton.GetId(),
                          reannounce_external)

            def bgalloc(self, frame=self):
                if frame.dow.storagewrapper is not None:
                    frame.dow.storagewrapper.bgalloc()
            wx.EVT_BUTTON(self.advBox, bgallocButton.GetId(), bgalloc)

            def closeAdv(evt, self=self):
                self.advBox.Close()

            def killAdv(evt, self=self):
                try:
                    self.advBox.RemoveIcon()
                except:
                    pass
                self.onDownRateSpinner()
                self.dow.spewflag.clear()
                self.advBox.Destroy()
                self.advBox = None
                if (self.advextannouncebox is not None):
                    try:
                        self.advextannouncebox.Close()
                    except wx.wxPyDeadObjectError:
                        pass
                    self.advextannouncebox = None
            wx.EVT_BUTTON(self.advBox, okButton.GetId(), closeAdv)
            wx.EVT_CLOSE(self.advBox, killAdv)

            self.advBox.Show()
            colSizer.Fit(panel)
            self.advBox.Fit()
            if self.dow:
                self.dow.spewflag.set()
        except:
            self.exception()

    def displayUsage(self, text):
        self.invokeLater(self.onDisplayUsage, [text])

    def onDisplayUsage(self, text):
        try:
            self.done(None)
            w = wx.wxFrame(
                None, -1, 'BITTORRENT USAGE',
                style=wx.wxDEFAULT_FRAME_STYLE | wx.wxFULL_REPAINT_ON_RESIZE)
            panel = wx.wxPanel(w, -1)
            sizer = wx.wxFlexGridSizer(cols=1)
            sizer.Add(wx.wxTextCtrl(panel, -1, text, size=(500, 300),
                      style=wx.wxTE_READONLY | wx.wxTE_MULTILINE))
            okButton = wx.wxButton(panel, -1, 'Ok')

            def closeUsage(self, frame=self):
                frame.usageBox.Close()
            wx.EVT_BUTTON(w, okButton.GetId(), closeUsage)

            def kill(self, frame=self):
                frame.usageBox.Destroy()
                frame.usageBox = None
            wx.EVT_CLOSE(w, kill)

            sizer.Add(okButton, 0, wx.wxALIGN_RIGHT)
            border = wx.wxBoxSizer(wx.wxHORIZONTAL)
            border.Add(sizer, 1, wx.wxEXPAND | wx.wxALL, 4)

            panel.SetSizer(border)
            panel.SetAutoLayout(True)

            border.Fit(panel)
            w.Fit()
            w.Show()
            self.usageBox = w
        except:
            self.exception()

    def updateStatus(self, dpflag=threading.Event(), fractionDone=None,
                     timeEst=None, downRate=None, upRate=None, activity=None,
                     statistics=None, spew=None, sizeDone=None, **kws):
        if activity is not None:
            self.activity = activity
        self.gui_fractiondone = fractionDone
        self.invokeLater(
            self.onUpdateStatus,
            [dpflag, timeEst, downRate, upRate, statistics, spew, sizeDone])

    def onUpdateStatus(self, dpflag, timeEst, downRate, upRate, statistics,
                       spew, sizeDone):
        if self.firstupdate:
            if not self.old_ratesettings:
                self.old_ratesettings = {}
            self.connChoice.SetStringSelection(self.old_ratesettings.get(
                'rate setting',
                self.configfileargs['gui_ratesettingsdefault']))
            self.onConnChoice(
                0, self.old_ratesettings.get('uploads'),
                self.old_ratesettings.get('max upload rate'))
            if 'max download rate' in self.old_ratesettings:
                self.dow.setDownloadRate(
                    self.old_ratesettings['max download rate'])
                if self.advBox:
                    self.downrateSpinner.SetValue(
                        self.old_ratesettings['max download rate'])
            self.firstupdate = False
            if self.advBox:
                self.dow.spewflag.set()
        if self.ispaused or statistics is None:
            self.setStatusIcon('startup')
        elif statistics.numPeers + statistics.numSeeds + \
                statistics.numOldSeeds == 0:
            if statistics.last_failed:
                self.setStatusIcon('disconnected')
            else:
                self.setStatusIcon('noconnections')
        elif not (statistics.external_connection_made or
                  self.configfileargs['gui_forcegreenonfirewall']):
            self.setStatusIcon('noincoming')
        elif ((statistics.numSeeds + statistics.numOldSeeds == 0)
              and (self.fin and statistics.numCopies < 1 or
                   not self.fin and statistics.numCopies2 < 1)):
            self.setStatusIcon('nocompletes')
        elif timeEst == 0 and sizeDone < self.torrentsize:
            self.setStatusIcon('nocompletes')
        else:
            self.setStatusIcon('allgood')
        if statistics is None:
            self.setgaugemode(-1)
        elif self.gui_fractiondone is None or self.gui_fractiondone == 1.0:
            self.setgaugemode(1)
        else:
            self.setgaugemode(0)

        if self.updateSliderFlag == 1:
            self.updateSliderFlag = 0
            newValue = (self.rateSpinner.GetValue() /
                        connChoices[
                            self.connChoice.GetSelection()
                        ]['rate'].get('div', 1))
            if self.rateslider.GetValue() != newValue:
                self.rateslider.SetValue(newValue)
        if self.updateSpinnerFlag == 1:
            self.updateSpinnerFlag = 0
            cc = connChoices[self.connChoice.GetSelection()]
            if 'rate' in cc:
                newValue = (self.rateslider.GetValue() *
                            cc['rate'].get('div', 1))
                if self.rateSpinner.GetValue() != newValue:
                    self.rateSpinner.SetValue(newValue)

        if self.fin:
            if statistics is None or statistics.numOldSeeds > 0 or \
                    statistics.numCopies > 1:
                self.gauge.SetValue(1000)
            else:
                self.gauge.SetValue(int(1000 * statistics.numCopies))
        elif self.gui_fractiondone is not None:
            gaugelevel = int(self.gui_fractiondone * 1000)
            self.gauge.SetValue(gaugelevel)
            if statistics is not None and statistics.downTotal is not None:
                if self.configfileargs['gui_displaymiscstats']:
                    self.frame.SetTitle(
                        '{:.1%} ({:.2f} MiB) {} - BitTorrent {}'.format(
                            float(gaugelevel) / 1000,
                            float(sizeDone) / (1 << 20),
                            self.filename, version))
                else:
                    self.frame.SetTitle('{:.1%} {} - BitTorrent {}'.format(
                        float(gaugelevel) / 1000, self.filename, version))
            else:
                self.frame.SetTitle('{:.0%} {} - BitTorrent {}'.format(
                    float(gaugelevel) / 1000, self.filename, version))
        if self.ispaused:
            self.timeText.SetLabel(hours(clock() - self.starttime) + ' /')
        elif timeEst is None:
            self.timeText.SetLabel(hours(clock() - self.starttime) + ' / ' +
                                   self.activity)
        else:
            self.timeText.SetLabel(hours(clock() - self.starttime) + ' / ' +
                                   hours(timeEst))
        if not self.ispaused:
            if downRate is not None:
                self.downRateText.SetLabel('{:.0f} kB/s'.format(
                    float(downRate) / 1000))
            if upRate is not None:
                self.upRateText.SetLabel('%.0f kB/s' % (float(upRate) / 1000))
        if self.taskbaricon:
            icontext = 'BitTorrent '
            if self.gui_fractiondone is not None and not self.fin:
                if statistics is not None and statistics.downTotal is not None:
                    icontext += ' {:.1%} ({:.2f} MiB)'.format(
                        self.gui_fractiondone, float(sizeDone) / (1 << 20))
                else:
                    icontext += '  {:.0%}'.format(self.gui_fractiondone)
            if upRate is not None:
                icontext += ' u:{:.0f} kB/s'.format(float(upRate) / 1000)
            if downRate is not None:
                icontext += ' d:{:.0f} kB/s'.format(float(downRate) / 1000)
            icontext += ' ' + self.filename
            try:
                if self.gui_fractiondone is None or \
                        self.gui_fractiondone == 1.0:
                    self.frame.tbicon.SetIcon(self.finicon, icontext)
                else:
                    self.frame.tbicon.SetIcon(self.icon, icontext)
            except:
                pass
        if statistics is not None:
            if self.autorate:
                self.rateSpinner.SetValue(statistics.upRate)
                self.connSpinner.SetValue(statistics.upSlots)

            downtotal = statistics.downTotal + self.old_download
            uptotal = statistics.upTotal + self.old_upload
            if self.configfileargs['gui_displaymiscstats']:
                self.downText.SetLabel('{:.2f} MiB'.format(
                    float(downtotal) / (1 << 20)))
                self.upText.SetLabel('{:.2f} MiB'.format(
                    float(uptotal) / (1 << 20)))
            if downtotal > 0:
                sharerating = float(uptotal) / downtotal
                if sharerating == 0:
                    shareSmiley = ''
                    color = 'Black'
                elif sharerating < 0.5:
                    shareSmiley = ':-('
                    color = 'Red'
                elif sharerating < 1.0:
                    shareSmiley = ':-|'
                    color = 'Orange'
                else:
                    shareSmiley = ':-)'
                    color = 'Forest Green'
            elif uptotal == 0:
                sharerating = None
                shareSmiley = ''
                color = 'Black'
            else:
                sharerating = None
                shareSmiley = '00 :-D'
                color = 'Forest Green'
            if sharerating is None:
                self.shareRatingText.SetLabel(shareSmiley)
            else:
                self.shareRatingText.SetLabel('{:.3f} {}'.format(
                    sharerating, shareSmiley))
            self.shareRatingText.SetForegroundColour(color)

            if self.configfileargs['gui_displaystats']:
                if not self.fin:
                    self.seedStatusText.SetLabel(
                        'connected to {:d} seeds; also seeing {:.3f} '
                        'distributed copies'.format(
                            statistics.numSeeds, statistics.numCopies2))
                else:
                    self.seedStatusText.SetLabel(
                        '{:d} seeds seen recently; also seeing {:.3f} '
                        'distributed copies'.format(
                            statistics.numOldSeeds, statistics.numCopies))
                self.peerStatusText.SetLabel(
                    'connected to {:d} peers with an average of {:.1%} '
                    'completed (total speed {:.0f} kB/s)'.format(
                        statistics.numPeers,
                        statistics.percentDone / 100,
                        float(statistics.torrentRate) / 1000))
        if ((clock() - self.lastError) > 300):
            self.errorText.SetLabel('')

        if (self.configfileargs['gui_displaymiscstats'] and
                statistics is not None and statistics.backgroundallocating):
            self.bgalloc_periods += 1
            if self.bgalloc_periods > 3:
                self.bgalloc_periods = 0
            self.bgallocText.SetLabel('ALLOCATING' + (' .' *
                                                      self.bgalloc_periods))
        elif self.dow.superseedflag.isSet():
            self.bgallocText.SetLabel('SUPER-SEED')
        else:
            self.bgallocText.SetLabel('')

        if spew is not None and (clock() - self.spewwait > 1):
            if self.advBox is not None:
                self.spewwait = clock()
                spewList = self.spewList
                spewlen = len(spew) + 2
                if statistics is not None:
                    kickbanlen = len(statistics.peers_kicked) + \
                        len(statistics.peers_banned)
                    if kickbanlen:
                        spewlen += kickbanlen + 1
                else:
                    kickbanlen = 0
                for x in range(spewlen - spewList.GetItemCount()):
                    i = wx.wxListItem()
                    spewList.InsertItem(i)
                for x in range(spewlen, spewList.GetItemCount()):
                    spewList.DeleteItem(len(spew) + 1)

                tot_uprate = 0.0
                tot_downrate = 0.0
                for x in range(len(spew)):
                    if (spew[x]['optimistic'] == 1):
                        a = '*'
                    else:
                        a = ' '
                    spewList.SetStringItem(x, 0, a)
                    spewList.SetStringItem(x, 1, spew[x]['id'])
                    spewList.SetStringItem(x, 2, spew[x]['ip'])
                    spewList.SetStringItem(x, 3, spew[x]['direction'])
                    if spew[x]['uprate'] > 100:
                        spewList.SetStringItem(x, 4, '{:.0f} kB/s'.format(
                            float(spew[x]['uprate']) / 1000))
                    else:
                        spewList.SetStringItem(x, 4, ' ')
                    tot_uprate += spew[x]['uprate']
                    if (spew[x]['uinterested'] == 1):
                        a = '*'
                    else:
                        a = ' '
                    spewList.SetStringItem(x, 5, a)
                    if (spew[x]['uchoked'] == 1):
                        a = '*'
                    else:
                        a = ' '
                    spewList.SetStringItem(x, 6, a)

                    if spew[x]['downrate'] > 100:
                        spewList.SetStringItem(x, 7, '{:.0f} kB/s'.format(
                            float(spew[x]['downrate']) / 1000))
                    else:
                        spewList.SetStringItem(x, 7, ' ')
                    tot_downrate += spew[x]['downrate']

                    if (spew[x]['dinterested'] == 1):
                        a = '*'
                    else:
                        a = ' '
                    spewList.SetStringItem(x, 8, a)
                    if (spew[x]['dchoked'] == 1):
                        a = '*'
                    else:
                        a = ' '
                    spewList.SetStringItem(x, 9, a)
                    if (spew[x]['snubbed'] == 1):
                        a = '*'
                    else:
                        a = ' '
                    spewList.SetStringItem(x, 10, a)
                    spewList.SetStringItem(x, 11, '{:.2f} MiB'.format(
                        float(spew[x]['dtotal']) / (1 << 20)))
                    if spew[x]['utotal'] is not None:
                        a = '{:.2f} MiB'.format(
                            float(spew[x]['utotal']) / (1 << 20))
                    else:
                        a = ''
                    spewList.SetStringItem(x, 12, a)
                    spewList.SetStringItem(
                        x, 13, '{:.1%}'.format(spew[x]['completed']))
                    if spew[x]['speed'] is not None:
                        a = '%.0f kB/s' % (float(spew[x]['speed']) / 1000)
                    else:
                        a = ''
                    spewList.SetStringItem(x, 14, a)

                x = len(spew)
                for i in range(15):
                    spewList.SetStringItem(x, i, '')

                x += 1
                spewList.SetStringItem(x, 2, '         TOTALS:')
                spewList.SetStringItem(x, 4, '{:.0f} kB/s'.format(
                    float(tot_uprate) / 1000))
                spewList.SetStringItem(x, 7, '{:.0f} kB/s'.format(
                    float(tot_downrate) / 1000))
                if statistics is not None:
                    spewList.SetStringItem(x, 11, '{:.2f} MiB'.format(
                        float(statistics.downTotal) / (1 << 20)))
                    spewList.SetStringItem(x, 12, '{:.2f} MiB'.format(
                        float(statistics.upTotal) / (1 << 20)))
                else:
                    spewList.SetStringItem(x, 11, '')
                    spewList.SetStringItem(x, 12, '')
                for i in (0, 1, 3, 5, 6, 8, 9, 10, 13, 14):
                    spewList.SetStringItem(x, i, '')

                if kickbanlen:
                    x += 1
                    for i in range(14):
                        spewList.SetStringItem(x, i, '')

                    for peer in statistics.peers_kicked:
                        x += 1
                        spewList.SetStringItem(x, 2, peer[0])
                        spewList.SetStringItem(x, 1, peer[1])
                        spewList.SetStringItem(x, 4, 'KICKED')
                        for i in (0, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14):
                            spewList.SetStringItem(x, i, '')

                    for peer in statistics.peers_banned:
                        x += 1
                        spewList.SetStringItem(x, 2, peer[0])
                        spewList.SetStringItem(x, 1, peer[1])
                        spewList.SetStringItem(x, 4, 'BANNED')
                        for i in (0, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14):
                            spewList.SetStringItem(x, i, '')

                if statistics is not None:
                    l1 = '{} currently downloading {:d} pieces ({:d} just ' \
                        'started), {:d} pieces partially retrieved'.format(
                            ' ' * 9, statistics.storage_active,
                            statistics.storage_new, statistics.storage_dirty)
                    if statistics.storage_isendgame:
                        l1 += ', endgame mode'
                    self.storagestats2.SetLabel(l1)
                    self.storagestats1.SetLabel(
                        '{} {:d} of {:d} pieces complete ({:d} just '
                        'downloaded), {:d} failed hash check, {}KiB redundant '
                        'data discarded'.format(
                            ' ' * 9, statistics.storage_numcomplete,
                            statistics.storage_totalpieces,
                            statistics.storage_justdownloaded,
                            statistics.storage_numflunked,
                            comma_format(int(statistics.discarded / 1024))))

        if (self.fileList is not None and statistics is not None and
                (statistics.filelistupdated.isSet() or self.refresh_details)):
            for i in range(len(statistics.filecomplete)):
                if self.dow.fileselector[i] == -1:
                    self.fileList.SetItemImage(i, 0, 0)
                    self.fileList.SetStringItem(i, 1, '')
                elif statistics.fileinplace[i]:
                    self.fileList.SetItemImage(i, 2, 2)
                    self.fileList.SetStringItem(i, 1, "done")
                elif statistics.filecomplete[i]:
                    self.fileList.SetItemImage(i, 1, 1)
                    self.fileList.SetStringItem(i, 1, "100%")
                else:
                    self.fileList.SetItemImage(i, 0, 0)
                    frac = statistics.fileamtdone[i]
                    if frac:
                        self.fileList.SetStringItem(
                            i, 1, '{:.0%}'.format(frac))
                    else:
                        self.fileList.SetStringItem(i, 1, '')

            statistics.filelistupdated.clear()
            self.refresh_details = False

        if self.configfile.configReset():     # Set everything invisible!

            self.dow.config['security'] = self.configfileargs['security']

            statsdisplayflag = self.configfileargs['gui_displaymiscstats']
            self.downTextLabel.Show(statsdisplayflag)
            self.upTextLabel.Show(statsdisplayflag)
            self.fileDestLabel.Show(statsdisplayflag)
            self.fileDestText.Show(statsdisplayflag)
            self.colSizer.Layout()

            self.downText.SetLabel('')          # blank these to flush them
            self.upText.SetLabel('')
            self.seedStatusText.SetLabel('')
            self.peerStatusText.SetLabel('')

            ratesettingsmode = self.configfileargs['gui_ratesettingsmode']
            ratesettingsflag1 = True    # \ settings
            ratesettingsflag2 = False   # / for 'basic'
            if ratesettingsmode == 'none':
                ratesettingsflag1 = False
            elif ratesettingsmode == 'full':
                ratesettingsflag2 = True
            self.connChoiceLabel.Show(ratesettingsflag1)
            self.connChoice.Show(ratesettingsflag1)
            self.rateSpinnerLabel.Show(ratesettingsflag2)
            self.rateSpinner.Show(ratesettingsflag2)
            self.rateLowerText.Show(ratesettingsflag2)
            self.rateUpperText.Show(ratesettingsflag2)
            self.rateslider.Show(ratesettingsflag2)
            self.connSpinnerLabel.Show(ratesettingsflag2)
            self.connSpinner.Show(ratesettingsflag2)
            self.connLowerText.Show(ratesettingsflag2)
            self.connUpperText.Show(ratesettingsflag2)
            self.connslider.Show(ratesettingsflag2)
            self.unlimitedLabel.Show(ratesettingsflag2)

            self.setgaugemode(None)

        self.frame.Layout()
        self.frame.Refresh()

        self.gui_fractiondone = None
        dpflag.set()

    def finished(self):
        self.fin = True
        self.invokeLater(self.onFinishEvent)

    def failed(self):
        self.fin = True
        self.invokeLater(self.onFailEvent)

    def error(self, errormsg):
        self.invokeLater(self.onErrorEvent, [errormsg])

    def onFinishEvent(self):
        self.activity = hours(clock() - self.starttime) + ' / ' + \
            'Download Succeeded!'
        self.cancelButton.SetLabel('Finish')
        self.gauge.SetValue(0)
        self.frame.SetTitle('{} - Upload - BitTorrent {}'.format(
            self.filename, version))
        try:
            self.frame.SetIcon(self.finicon)
        except:
            pass
        if self.taskbaricon:
            self.frame.tbicon.SetIcon(self.finicon, "BitTorrent - Finished")
        self.downRateText.SetLabel('')

    def onFailEvent(self):
        if not self.shuttingdown:
            self.timeText.SetLabel(hours(clock() - self.starttime) + ' / ' +
                                   'Failed!')
            self.activity = 'Failed!'
            self.cancelButton.SetLabel('Close')
            self.gauge.SetValue(0)
            self.downRateText.SetLabel('')
            self.setStatusIcon('startup')

    def onErrorEvent(self, errormsg):
        # indent at least 2 spaces means a warning message
        if errormsg[:2] == '  ':
            self.errorText.SetLabel(errormsg)
            self.lastError = clock()
        else:
            self.errorText.SetLabel(time.strftime('ERROR (%x %X) -\n') +
                                    errormsg)
            self.lastError = clock()

    def chooseFile(self, default, size, saveas, dir):
        f = threading.Event()
        bucket = [None]
        self.invokeLater(self.onChooseFile,
                         [default, bucket, f, size, dir, saveas])
        f.wait()
        return bucket[0]

    def onChooseFile(self, default, bucket, f, size, dir, saveas):
        if saveas == '':
            if self.configfileargs['gui_default_savedir'] != '':
                start_dir = self.configfileargs['gui_default_savedir']
            else:
                start_dir = self.configfileargs['last_saved']
            if not os.path.isdir(start_dir):    # if it's not set properly
                start_dir = '/'    # yes, this hack does work in Windows
            if dir:
                start_dir1 = start_dir
                if os.path.isdir(os.path.join(start_dir, default)):
                    start_dir = os.path.join(start_dir, default)
                dl = wx.wxDirDialog(
                    self.frame, 'Choose a directory to save to, pick a '
                    'partial download to resume', defaultPath=start_dir,
                    style=wx.wxDD_DEFAULT_STYLE | wx.wxDD_NEW_DIR_BUTTON)
            else:
                dl = wx.wxFileDialog(
                    self.frame, 'Choose file to save as, pick a partial '
                    'download to resume', defaultDir=start_dir,
                    defaultFile=default, wildcard='*', style=wx.wxSAVE)

            if dl.ShowModal() != wx.wxID_OK:
                f.set()
                self.done(None)
                return

            d = dl.GetPath()
            if d == start_dir:
                d = start_dir1
            bucket[0] = d
            d1, d2 = os.path.split(d)
            if d2 == default:
                d = d1
            self.configfile.WriteLastSaved(d)

        else:
            bucket[0] = saveas
            default = os.path.basename(saveas)

        self.onChooseFileDone(default, size)
        f.set()

    def ChooseFileDone(self, name, size):
        self.invokeLater(self.onChooseFileDone, [name, size])

    def onChooseFileDone(self, name, size):
        self.torrentsize = size
        lname = os.path.basename(name)
        self.filename = lname
        self.fileNameText.SetLabel('%s' % (lname))
        self.fileSizeText.SetLabel('(%.2f MiB)' % (float(size) / (1 << 20)))
        self.timeText.SetLabel(hours(clock() - self.starttime) + ' / ' +
                               self.activity)
        self.fileDestText.SetLabel(name)
        self.frame.SetTitle(lname + '- BitTorrent ' + version)

        minsize = self.fileNameText.GetBestSize()
        if (not self.configfileargs['gui_stretchwindow'] or
                minsize.GetWidth() < self.addwidth):
            minsize.SetWidth(self.addwidth)
        self.fnsizer.SetMinSize(minsize)
        minsize.SetHeight(self.fileSizeText.GetBestSize().GetHeight())
        self.fnsizer2.SetMinSize(minsize)
        minsize.SetWidth(minsize.GetWidth() + (self.FONT * 8))
        minsize.SetHeight(self.fileNameText.GetBestSize().GetHeight() +
                          self.fileSizeText.GetBestSize().GetHeight())
        minsize.SetHeight(2 * self.errorText.GetBestSize().GetHeight())
        self.errorTextSizer.SetMinSize(minsize)
        self.topboxsizer.SetMinSize(minsize)

        # Kludge to make details and about catch the event
        self.frame.SetSize((self.frame.GetSizeTuple()[0] + 1,
                            self.frame.GetSizeTuple()[1] + 1))
        self.frame.SetSize((self.frame.GetSizeTuple()[0] - 1,
                            self.frame.GetSizeTuple()[1] - 1))
        self.colSizer.Fit(self.frame)
        self.frame.Layout()
        self.frame.Refresh()

    def newpath(self, path):
        self.invokeLater(self.onNewpath, [path])

    def onNewpath(self, path):
        self.fileDestText.SetLabel(path)

    def pause(self, event):
        self.invokeLater(self.onPause)

    def onPause(self):
        if not self.dow:
            return
        if self.ispaused:
            self.ispaused = False
            self.pauseButton.SetLabel('Pause')
            self.dow.Unpause()
        else:
            if self.dow.Pause():
                self.ispaused = True
                self.pauseButton.SetLabel('Resume')
                self.downRateText.SetLabel(' ')
                self.upRateText.SetLabel(' ')
                self.setStatusIcon('startup')

    def done(self, event):
        self.uiflag.set()
        self.flag.set()
        self.shuttingdown = True

        try:
            self.frame.tbicon.RemoveIcon()
        except:
            pass
        try:
            self.frame.tbicon.Destroy()
        except:
            pass
        try:
            self.detailBox.Close()
        except:
            self.detailBox = None
        try:
            self.aboutBox.Close()
        except:
            self.aboutBox = None
        try:
            self.creditsBox.Close()
        except:
            self.creditsBox = None
        try:
            self.advBox.Close()
        except:
            self.advBox = None
        try:
            self.statusIconHelpBox.Close()
        except:
            self.statusIconHelpBox = None
        try:
            self.frame.RemoveIcon()
        except:
            pass

        self.frame.Destroy()

    def exception(self):
        data = StringIO()
        traceback.print_exc(file=data)
        print data.getvalue()   # report exception here too
        self.on_errorwindow(data.getvalue())

    def errorwindow(self, err):
        self.invokeLater(self.on_errorwindow, [err])

    def on_errorwindow(self, err):
        if self._errorwindow is None:
            w = wx.wxFrame(
                None, -1, 'BITTORRENT ERROR', size=(1, 1),
                style=wx.wxDEFAULT_FRAME_STYLE | wx.wxFULL_REPAINT_ON_RESIZE)
            panel = wx.wxPanel(w, -1)

            sizer = wx.wxFlexGridSizer(cols=1)
            t = ('BitTorrent ' + version + '\n' +
                 'OS: ' + sys.platform + '\n' +
                 'Python version: ' + sys.version + '\n' +
                 'wxWindows version: ' + wx.wxVERSION_STRING + '\n')
            try:
                t += 'Allocation method: ' + self.config['alloc_type']
                if self.dow.storagewrapper.bgalloc_active:
                    t += '*'
                t += '\n'
            except:
                pass
            sizer.Add(wx.wxTextCtrl(panel, -1, t + '\n' + err, size=(500, 300),
                      style=wx.wxTE_READONLY | wx.wxTE_MULTILINE))

            sizer.Add(wx.wxStaticText(panel, -1,
                      '\nHelp us iron out the bugs in the engine!'))
            linkMail = wx.wxStaticText(
                panel, -1, 'Please report this error to ' + report_email)
            linkMail.SetFont(wx.wxFont(self.FONT, wx.wxDEFAULT, wx.wxNORMAL,
                             wx.wxNORMAL, True))
            linkMail.SetForegroundColour('Blue')
            sizer.Add(linkMail)

            def maillink(self):
                threading.Thread(
                    target=open_new(
                        "mailto:{}?subject=autobugreport".format(report_email))
                ).start()
            wx.EVT_LEFT_DOWN(linkMail, maillink)

            border = wx.wxBoxSizer(wx.wxHORIZONTAL)
            border.Add(sizer, 1, wx.wxEXPAND | wx.wxALL, 4)

            panel.SetSizer(border)
            panel.SetAutoLayout(True)

            w.Show()
            border.Fit(panel)
            w.Fit()
            self._errorwindow = w


class btWxApp(wx.wxApp):
    def __init__(self, x, params):
        self.params = params
        wx.wxApp.__init__(self, x)

    def OnInit(self):
        doneflag = threading.Event()
        self.configfile = configReader()
        d = DownloadInfoFrame(doneflag, self.configfile)
        self.SetTopWindow(d.frame)
        if len(self.params) == 0:
            b = wx.wxFileDialog(d.frame, 'Choose .torrent file to use',
                                defaultDir='', defaultFile='',
                                wildcard='*.torrent', style=wx.wxOPEN)

            if b.ShowModal() == wx.wxID_OK:
                self.params.append(b.GetPath())

        thread = threading.Thread(
            target=next, args=[self.params, d, doneflag, self.configfile])
        thread.setDaemon(False)
        thread.start()
        return 1


def run(params):
    if WXPROFILER:
        import profile
        import pstats
        p = profile.Profile()
        p.runcall(_run, params)
        log_fname = 'profile_data_wx.' + time.strftime('%y%m%d%H%M%S') + '.txt'
        with open(log_fname, 'a') as log:
            normalstdout, sys.stdout = sys.stdout, log
            pstats.Stats(p).strip_dirs().sort_stats('time').print_stats()
            sys.stdout = normalstdout
    else:
        _run(params)


def _run(params):
    app = btWxApp(0, params)
    app.MainLoop()


def next(params, d, doneflag, configfile):
    if PROFILER:
        import profile
        import pstats
        p = profile.Profile()
        p.runcall(_next, params, d, doneflag, configfile)
        log_fname = 'profile_data.' + time.strftime('%y%m%d%H%M%S') + '.txt'
        with open(log_fname, 'a') as log:
            normalstdout, sys.stdout = sys.stdout, log
            pstats.Stats(p).strip_dirs().sort_stats('time').print_stats()
            sys.stdout = normalstdout
    else:
        _next(params, d, doneflag, configfile)


def _next(params, d, doneflag, configfile):
    err = False
    try:
        while 1:
            try:
                config = parse_params(params, configfile.config)
            except ValueError as e:
                d.error('error: ' + str(e) +
                        '\nrun with no args for parameter explanations')
                break
            if not config:
                d.displayUsage(get_usage(presets=configfile.config))
                break

            myid = createPeerID()
            random.seed(myid)

            rawserver = RawServer(doneflag, config['timeout_check_interval'],
                                  config['timeout'],
                                  ipv6_enable=config['ipv6_enabled'],
                                  failfunc=d.error, errorfunc=d.errorwindow)

            upnp_type = UPnP_test(config['upnp_nat_access'])
            while True:
                try:
                    listen_port = rawserver.find_and_bind(
                        config['minport'], config['maxport'], config['bind'],
                        ipv6_socket_style=config['ipv6_binds_v4'],
                        upnp=upnp_type, randomizer=config['random_port'])
                    break
                except socket.error as e:
                    if upnp_type and e == UPnP_ERROR:
                        d.error('WARNING: COULD NOT FORWARD VIA UPnP')
                        upnp_type = 0
                        continue
                    d.error("Couldn't listen - " + str(e))
                    d.failed()
                    return
            d.connection_stats = rawserver.get_stats()

            response = get_response(config['responsefile'], config['url'],
                                    d.error)
            if not response:
                break

            infohash = hashlib.sha1(bencode(response['info'])).digest()

            torrentdata = configfile.getTorrentData(infohash)
            if torrentdata:
                oldsave = torrentdata.get('saved as')
                d.old_ratesettings = torrentdata.get('rate settings')
                s = torrentdata.get('stats')
                if s:
                    d.old_upload = s['uploaded']
                    d.old_download = s['downloaded']
            else:
                oldsave = None

            dow = BT1Download(
                d.updateStatus, d.finished, d.error, d.errorwindow, doneflag,
                config, response, infohash, myid, rawserver, listen_port,
                configfile.getConfigDir())
            d.dow = dow

            if config['gui_saveas_ask'] == 1:
                oldsave = None
            if oldsave:
                if not dow.checkSaveLocation(oldsave):
                    oldsave = None
            if oldsave:
                def choosefile(default, size, saveas, dir, oldsave=oldsave):
                    d.ChooseFileDone(oldsave, size)
                    return oldsave
            elif config['gui_saveas_ask'] == 0:
                def choosefile(default, size, saveas, dir,
                               spot=config['gui_default_savedir']):
                    spot = os.path.join(spot, default)
                    d.ChooseFileDone(spot, size)
                    return spot
            else:
                choosefile = d.chooseFile
            savedas = dow.saveAs(choosefile, d.newpath)
            if not savedas:
                break

            if not dow.initFiles(old_style=True):
                break
            if not dow.startEngine():
                dow.shutdown()
                break
            dow.startRerequester()
            dow.autoStats()

            if not dow.am_I_finished():
                d.updateStatus(activity='connecting to peers')
            rawserver.listen_forever(dow.getPortHandler())

            ratesettings = {
                'rate setting': d.current_ratesetting,
                'max download rate': config['max_download_rate']
            }
            if d.current_ratesetting != 'automatic':
                ratesettings['uploads'] = config['min_uploads']
                ratesettings['max upload rate'] = config['max_upload_rate']
            up, dn = dow.get_transfer_stats()
            stats = {
                'uploaded': up + d.old_upload,
                'downloaded': dn + d.old_download
            }
            torrentdata = {
                'saved as': savedas,
                'rate settings': ratesettings,
                'stats': stats
            }
            dow.shutdown(torrentdata)
            break
    except:
        err = True
        data = StringIO()
        traceback.print_exc(file=data)
        print data.getvalue()   # report exception here too
        d.errorwindow(data.getvalue())
    try:
        rawserver.shutdown()
    except:
        pass
    if not d.fin:
        d.failed()
    if err:
        # this will make the app stick in the task manager, but so be it
        time.sleep(3600 * 24 * 30)

if __name__ == '__main__':
    if sys.argv[1:] == ['--version']:
        print version
        sys.exit(0)
    run(sys.argv[1:])
