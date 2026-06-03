# -*- coding: utf-8 -*-
'''
Created in 2016/03/28
@author: xjunior
'''
import sys
import time
import uuid
from demo.util.SendRestUtil import SendRestUtil
# 看demo所在目录，添加路径
sys.path.append('../../..')
from demo.util import SignGenUtil

# 有些输出是中文字符，统一设置一下编码
# reload(sys)
# sys.setdefaultencoding('utf8')
'''
利用REST进行站点、指数资料数据保存
'''
if __name__ == '__main__':
    # 1. 调用方法的参数定义，并赋值
    # 1.1 接口url
    # 1.2 用户名&密码
    # 1.3 接口ID
    # 1.4 必选参数（按需加可选参数）
    #     资料代码：城镇天气预报产品要素资料(测试)
    #     要素字段代码(非键值):年、月、日、时、预报时效、风向、风的转向、风力、转后风力、最高温度、最低度温
    #     要素字段代码（键值）

    # 服务节点
    serviceNodeId = 'NMIC_MUSIC_CMADAAS'
    # 接口服务端IP和端口
    serviceIp = '10.40.17.54:80'
    # 用户名&密码
    userId = 'NMIC_XTS_CMADAASTEST'
    pwd = 'test1234'
    # 序列化格式
    #dataFormat = 'html'
    # 接口url
    baseUrl = 'http://' + serviceIp + '/music-ws/write?\
serviceNodeId=' + serviceNodeId + '\
&userId=' + userId + '\
&interfaceId=saveStationData\
&dataCode=SEVP_WEFC_ACPP_STORE\
&elements=Datetime,Station_Id_C,Year,Mon,Day,Hour,Validtime,WIN_D,WIN_Turn,WINF,WINF_Turn,TEM_Max_2m,TEM_Min_2m'

    # 接口url一次拼接
    #baseUrl = baseUrl + dataFormat
    # 生成时间戳和uuid，并拼接接口url
    timestamp = str(int(round(time.time() * 1000)))
    nonce = str(uuid.uuid1())
    baseUrl += '&timestamp=' + timestamp
    baseUrl += '&nonce=' + nonce
    # 生成sign
    signParams = {'serviceNodeId': serviceNodeId,
                  'userId': userId,
                  'interfaceId': 'saveStationData',
                  'dataCode': 'SEVP_WEFC_ACPP_STORE',
                  'elements': 'Datetime,Station_Id_C,Year,Mon,Day,Hour,Validtime,WIN_D,WIN_Turn,WINF,WINF_Turn,TEM_Max_2m,TEM_Min_2m',
                  'timestamp': timestamp,
                  'nonce': nonce,
                  'pwd': pwd,
                  }
    signUtil = SignGenUtil.SignGenUtil()
    sign = signUtil.getSign(signParams)
    if (sign == ""):
        print("generate sign is None")
    # 拼接sign
    baseUrl+='&sign=' + sign
    # print(baseUrl)
    inString ="20160328060000,54323,2016,3,28,6,72,5,5,0,0,2.0000,-50.0000;20160329060000,54324,2016,3,29,6,96,4,4,1,1,2.0000,-50.0000"
    # 2.1 二维数组 等同于list列表： [[ "20160328060000,54323,2016,3,28,6,72,5,5,0,0,2.0000,-50.0000;20160329060000,54324,2016,3,29,6,96,4,4,1,1,2.0000,-50.0000"]]
    # 2.1.1 二维数组的第二维
    inArray2D_1 = []    
    inArray2D_1.append(inString)
    # 2.1.2 二维数组的第一维 
    inArray2D = []    
    inArray2D.append(inArray2D_1)
    #写入数据格式转换
    storeString = SendRestUtil.getPbStoreArray2DString(inArray2D,0,None)
    #发送数据写入请求
    requestInfo = SendRestUtil.sendRest(baseUrl, storeString)
    #输出写入结果
    print (requestInfo)