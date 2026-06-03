#!/usr/bin/python
# -*- coding: UTF-8 -*-
'''
send rest util class
Created on 2020年3月28日
@author: wufy

'''
from cma.music import DataFormatUtils,apiinterface_pb2
from cma.music.MusicDataBean import RequestInfo
import pycurl
import io
import json

class SendRestUtil(object):
    getwayFlag = "\"flag\":\"slb\""; #网关返回错误标识
    
    def __init__(self):
        '''
        Constructor
        '''
    
    def getPbStoreArray2DString(self, inArray2D, iFlag, inFilePaths):
        '''
                     获取写入字符串
        '''
        #由StoreArray2D对象生成storeInfos
        pbStoreArray2D = apiinterface_pb2.StoreArray2D()

        #获得inArray2D行列
        row = len(inArray2D)
        col = len(inArray2D[0])
        #设置storeInfos的属性值
        pbStoreArray2D.row = row
        pbStoreArray2D.col = col
        pbStoreArray2D.fileflag = iFlag
        if(iFlag==1):
            pbStoreArray2D.is_backstage = self.storeBackstageCur
            if(self.storeBackstageCur==1):               
                pbStoreArray2D.client_mount_path = self.localMountCur
                pbStoreArray2D.server_mount_path = self.serverMountPathCur

        # 日期 和 站点
        for i in range(row):
            for j in range(col):
                pbStoreArray2D.data.append(inArray2D[i][j])
    
        #上传文件时的本地路径
        if(iFlag ==1):
            for i in range(len(inFilePaths)):
                pbStoreArray2D.filenames.append(inFilePaths[i])

        return pbStoreArray2D.SerializeToString()
    
    def sendRest(self,newUrl,storeString):
        requestInfo = RequestInfo()
        try:
            buf = io.BytesIO()  
            response = pycurl.Curl()
            response.setopt(pycurl.URL, newUrl)
            response.setopt(pycurl.POST,1)
            storeNewString = 'postdata='.encode(encoding='utf_8', errors='strict')+storeString
            response.setopt(pycurl.POSTFIELDS,storeNewString)
            response.setopt(pycurl.CONNECTTIMEOUT, self.connTimeout)
            response.setopt(pycurl.TIMEOUT, self.readTimeout)
            response.setopt(pycurl.WRITEFUNCTION, buf.write)
            #response.setopt(pycurl.WRITEDATA, value)
            response.perform()
            response.close()
        except: #http error
            print ("Error retrieving data")
            requestInfo.errorCode = self.OTHER_ERROR
            requestInfo.errorMessage = "Error retrieving data"
            return requestInfo
            
        RetByteArraydata = buf.getvalue()
        if(RetByteArraydata.__contains__(self.getwayFlag.encode(encoding='utf_8', errors='strict'))): #网关错误
            getwayInfo = json.loads(RetByteArraydata)
            if(getwayInfo is None):
                requestInfo.errorCode = self.OTHER_ERROR
                requestInfo.errorMessage = "parse getway return string error!"
            else:
                requestInfo.errorCode = getwayInfo['returnCode']
                requestInfo.errorMessage = getwayInfo['returnMessage']
        else: #服务端返回结果
            # 反序列化为proto的结果
            pbRequestInfo = apiinterface_pb2.RequestInfo()
            pbRequestInfo.ParseFromString(RetByteArraydata)
            # 格式转换，生成music的结果
            utils = DataFormatUtils.Utils()
            requestInfo = utils.getRequestInfo(pbRequestInfo)
            
        return requestInfo
    