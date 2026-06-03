#!/usr/bin/python
# -*- coding: UTF-8 -*-
'''
Sign generate util class
Created on 2020年3月28日
@author: wufy

'''

import hashlib

class SignGenUtil(object):
    
    def __init__(self):
        '''
        Constructor
        '''
    
    def getSign(self,signParams):
        '''
                    生成sign标签
        '''
        sign = ""
        try:
            paramString = ""
            if( "params" in signParams):
                paramsVal = signParams.pop("params")
                keyValList = paramsVal.split("&")
                for keyVal in keyValList:
                    signParams[keyVal.split("=")[0]] = keyVal.split("=")[1]
                
            #keys = signParams.keys()
            #keys.sort()
            keys = sorted(signParams)
            for key in keys:
                paramString = paramString + key + "=" + signParams.get(key) + "&"
            if(paramString):
                paramString = paramString[:-1]
            
            #进行MD5运算
            sign = hashlib.md5(paramString.encode(encoding='UTF-8')).hexdigest().upper()
        except:
            return("generate sign error")
        
        return sign  