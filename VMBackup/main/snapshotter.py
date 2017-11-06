#!/usr/bin/env python
#
# VM Backup extension
#
# Copyright 2014 Microsoft Corporation
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

import os
try:
    import urlparse as urlparser
except ImportError:
    import urllib.parse as urlparser
import traceback
import datetime
try:
    import ConfigParser as ConfigParsers
except ImportError:
    import configparser as ConfigParsers
import multiprocessing as mp
import datetime
import json
from common import CommonVariables
from HttpUtil import HttpUtil
from Utils import Status
from Utils import HandlerUtil
from fsfreezer import FsFreezer
from guestsnapshotter import GuestSnapshotter
from hostsnapshotter import HostSnapshotter

class Snapshotter(object):
    """description of class"""
    def __init__(self, logger, hutil , freezer, para_parser):
        self.logger = logger
        self.configfile = '/etc/azure/vmbackup.conf'
        self.hutil = hutil
        self.freezer = freezer
        self.para_parser = para_parser
        self.takeSnapshotFrom = para_parser.takeSnapshotFrom

    def doSnapshot(self):
        run_result = CommonVariables.success
        run_status = 'success'

        if(self.takeSnapshotFrom == CommonVariables.onlyGuest):
            run_result, run_status, snapshot_info_array = self.takeSnapshotFromOnlyGuest()
        elif(self.takeSnapshotFrom == CommonVariables.firstGuestThenHost):
            run_result, run_status, snapshot_info_array = self.takeSnapshotFromFirstGuestThenHost()

        return run_result, run_status, snapshot_info_array
    
    def freeze(self):
        try:
            timeout = self.hutil.get_value_from_configfile('timeout')
            if(timeout == None):
                timeout = str(60)
            time_before_freeze = datetime.datetime.now()
            freeze_result = self.freezer.freeze_safe(timeout) 
            time_after_freeze = datetime.datetime.now()
            HandlerUtil.HandlerUtility.add_to_telemetery_data("FreezeTime", str(time_after_freeze-time_before_freeze-datetime.timedelta(seconds=5)))
            run_result = CommonVariables.success
            run_status = 'success'
            all_failed= False
            is_inconsistent =  False
            self.logger.log('T:S freeze result ' + str(freeze_result))
            if(freeze_result is not None and len(freeze_result.errors) > 0):
                run_result = CommonVariables.FailedFsFreezeFailed
                run_status = 'error'
                error_msg = 'T:S Enable failed with error: ' + str(freeze_result)
                self.hutil.SetExtErrorCode(ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.FailedRetryableFsFreezeFailed)
                error_msg = error_msg + ExtensionErrorCodeHelper.ExtensionErrorCodeHelper.StatusCodeStringBuilder(self.hutil.ExtErrorCode)
                self.logger.log(error_msg, True, 'Warning')
                if(self.hutil.get_value_from_configfile('doseq') == '2'):
                    self.hutil.set_value_to_configfile('doseq', '0')
        except Exception as e:
            if(self.hutil.get_value_from_configfile('doseq') == '2'):
                self.hutil.set_value_to_configfile('doseq', '0')
            errMsg = 'Failed to do the freeze with error: %s, stack trace: %s' % (str(e), traceback.format_exc())
            self.logger.log(errMsg, True, 'Error')
            run_result = CommonVariables.error
            run_status = 'error'
        
        return run_result, run_status
    
    def check_snapshot_array_fail(self, snapshot_info_array):
        snapshot_array_fail = False
        if snapshot_info_array is not None and snapshot_info_array !=[]:
            for snapshot_index in range(len(snapshot_info_array)):
                if(snapshot_info_array[snapshot_index].isSuccessful == False):
                    backup_logger.log('T:S  snapshot failed at index ' + str(snapshot_index), True)
                    snapshot_array_fail = True
                    break
        return snapshot_array_fail

    def takeSnapshotFromOnlyGuest(self):
        run_result = CommonVariables.success
        run_status = 'success'

        all_failed= False
        is_inconsistent =  False
        snapshot_info_array = None
        try:
            run_result, run_status = self.freeze()
            if(run_result == CommonVariables.success):
                HandlerUtil.HandlerUtility.add_to_telemetery_data("SnapshotTakenFrom", "Guest")
                snap_shotter = GuestSnapshotter(self.logger)
                self.logger.log('T:S doing snapshot now...')
                time_before_snapshot = datetime.datetime.now()
                snapshot_result,snapshot_info_array, all_failed, is_inconsistent, unable_to_sleep  = snap_shotter.snapshotall(self.para_parser, self.freezer)
                time_after_snapshot = datetime.datetime.now()
                HandlerUtil.HandlerUtility.add_to_telemetery_data("SnapshotTime", str(time_after_snapshot-time_before_snapshot))
                self.logger.log('T:S snapshotall ends...', True)
                if(self.hutil.get_value_from_configfile('doseq') == '2'):
                    self.hutil.set_value_to_configfile('doseq', '0')
                if(snapshot_result is not None and len(snapshot_result.errors) > 0):
                    if unable_to_sleep:
                        run_result = CommonVariables.error
                        run_status = 'error'
                        error_msg = 'T:S Enable failed with error: ' + str(snapshot_result)
                        self.logger.log(error_msg, True, 'Warning')
                    elif is_inconsistent == True :
                        self.hutil.set_value_to_configfile('doseq', '1') 
                        run_result = CommonVariables.error
                        run_status = 'error'
                        error_msg = 'T:S Enable failed with error: ' + str(snapshot_result)
                        self.logger.log(error_msg, True, 'Warning')
                    else:
                        error_msg = 'T:S snapshot result: ' + str(snapshot_result)
                        run_result = CommonVariables.FailedRetryableSnapshotFailedNoNetwork
                        if all_failed:
                           self.hutil.SetExtErrorCode(ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.FailedRetryableSnapshotFailedNoNetwork)
                           error_msg = error_msg + ExtensionErrorCodeHelper.ExtensionErrorCodeHelper.StatusCodeStringBuilder(self.hutil.ExtErrorCode)
                        else:
                            self.hutil.SetExtErrorCode(ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.FailedRetryableSnapshotFailedRestrictedNetwork)
                            error_msg = error_msg + ExtensionErrorCodeHelper.ExtensionErrorCodeHelper.StatusCodeStringBuilder(self.hutil.ExtErrorCode)
                        run_status = 'error'
                        self.logger.log(error_msg, True, 'Error')
                elif self.check_snapshot_array_fail(snapshot_info_array) == True:
                    run_result = CommonVariables.error
                    run_status = 'error'
                    error_msg = 'T:S Enable failed with error in snapshot_array index'
                    self.logger.log(error_msg, True, 'Error')
        except Exception as e:
            if(self.hutil.get_value_from_configfile('doseq') == '2'):
                self.hutil.set_value_to_configfile('doseq', '0')
            errMsg = 'Failed to do the snapshot with error: %s, stack trace: %s' % (str(e), traceback.format_exc())
            self.logger.log(errMsg, True, 'Error')
            run_result = CommonVariables.error
            run_status = 'error'

        return run_result, run_status, snapshot_info_array
    
    def takeSnapshotFromFirstGuestThenHost(self):
        run_result = CommonVariables.success
        run_status = 'success'

        all_failed= False
        is_inconsistent =  False
        snapshot_info_array = None
        try:
            run_result, run_status = self.freeze()
            if(run_result == CommonVariables.success):
                HandlerUtil.HandlerUtility.add_to_telemetery_data("SnapshotTakenFrom", "Guest")
                snap_shotter = GuestSnapshotter(self.logger)
                self.logger.log('T:S doing snapshot now...')
                time_before_snapshot = datetime.datetime.now()
                snapshot_result,snapshot_info_array, all_failed, is_inconsistent, unable_to_sleep  = snap_shotter.snapshotall(self.para_parser, self.freezer)
                time_after_snapshot = datetime.datetime.now()
                HandlerUtil.HandlerUtility.add_to_telemetery_data("SnapshotTime", str(time_after_snapshot-time_before_snapshot))
                self.logger.log('T:S snapshotall ends...', True)
                if(self.hutil.get_value_from_configfile('doseq') == '2'):
                    self.hutil.set_value_to_configfile('doseq', '0')
                if(snapshot_result is not None and len(snapshot_result.errors) > 0):
                    if unable_to_sleep:
                        run_result = CommonVariables.error
                        run_status = 'error'
                        error_msg = 'T:S Enable failed with error: ' + str(snapshot_result)
                        self.logger.log(error_msg, True, 'Warning')
                    elif is_inconsistent == True :
                        self.hutil.set_value_to_configfile('doseq', '1') 
                        run_result = CommonVariables.error
                        run_status = 'error'
                        error_msg = 'T:S Enable failed with error: ' + str(snapshot_result)
                        self.logger.log(error_msg, True, 'Warning')
                    else:
                        error_msg = 'T:S snapshot result: ' + str(snapshot_result)
                        run_result = CommonVariables.FailedRetryableSnapshotFailedNoNetwork
                        if all_failed:
                           self.hutil.SetExtErrorCode(ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.FailedRetryableSnapshotFailedNoNetwork)
                           error_msg = error_msg + ExtensionErrorCodeHelper.ExtensionErrorCodeHelper.StatusCodeStringBuilder(self.hutil.ExtErrorCode)
                        else:
                            self.hutil.SetExtErrorCode(ExtensionErrorCodeHelper.ExtensionErrorCodeEnum.FailedRetryableSnapshotFailedRestrictedNetwork)
                            error_msg = error_msg + ExtensionErrorCodeHelper.ExtensionErrorCodeHelper.StatusCodeStringBuilder(self.hutil.ExtErrorCode)
                        run_status = 'error'
                        self.logger.log(error_msg, True, 'Error')
                elif self.check_snapshot_array_fail(snapshot_info_array) == True:
                    run_result = CommonVariables.error
                    run_status = 'error'
                    error_msg = 'T:S Enable failed with error in snapshot_array index'
                    self.logger.log(error_msg, True, 'Error')
        except Exception as e:
            if(self.hutil.get_value_from_configfile('doseq') == '2'):
                self.hutil.set_value_to_configfile('doseq', '0')
            errMsg = 'Failed to do the snapshot with error: %s, stack trace: %s' % (str(e), traceback.format_exc())
            self.logger.log(errMsg, True, 'Error')
            run_result = CommonVariables.error
            run_status = 'error'

        all_failed= False
        is_inconsistent =  False
        snapshot_info_array = None
        if(run_result != CommonVariables.success):
            HandlerUtil.HandlerUtility.add_to_telemetery_data("SnapshotTakenFrom", "Host")
            run_result, run_status = self.freeze()
            if(run_result == CommonVariables.success):
                snap_shotter = HostSnapshotter(self.logger)
                self.logger.log('T:S doing snapshot now...')
                time_before_snapshot = datetime.datetime.now()
                snapshot_call_failed,snapshot_info_array, all_failed, is_inconsistent, unable_to_sleep  = snap_shotter.snapshotall(self.para_parser, self.freezer)
                time_after_snapshot = datetime.datetime.now()
                HandlerUtil.HandlerUtility.add_to_telemetery_data("SnapshotTime", str(time_after_snapshot-time_before_snapshot))
                self.logger.log('T:S snapshotall ends...', True)
                if( not (snapshot_call_failed or self.check_snapshot_array_fail(snapshot_info_array))):
                    run_result = CommonVariables.success
                    run_status = 'success'
                    error_msg = 'Enable Succeeded'
                    self.logger.log("T:S " + error_msg, True)

        return run_result, run_status, snapshot_info_array
