# coding=utf8
'''
Modified in 2016/03/28

@author: xjunior
'''
from cma.music.DataQueryClient import DataQueryClient
if __name__ == "__main__":
    '''
    格点场要素获取（切块），返回RetGridArray2D对象
    '''
    # 1. 定义client对象  
    client = DataQueryClient()
    
    # 2. 调用方法的参数定义，并赋值
    # 2.1 用户名&密码 
    userId = "NMIC_XTS_CMADAASTEST" 
    pwd = "test1234" 
        
    # 2.2  接口ID     
    interfaceId = "getNafpEleGridInRectByTimeAndLevelAndValidtime"
        
    # 2.3  接口参数，多个参数间无顺序     
    # 必选参数    (1)资料:T639高精度格点产品(东北半球); (2)起报时间; (3)起始、终止预报时效;
    #          (4)经纬度点,北京(纬度39.8，经度116.4667)、上海(纬度31.2,经度121.4333);
    #          (5)预报要素（单个):气温; (6)预报层次(单个):850hpa。
    params = {'dataCode':"NAFP_FOR_FTM_LOW_EC_GLB",\
              'time':"20190601000000",\
              'validTime':"24",\
              'minLat':"39",'maxLat':"42",\
              'minLon':"115",'maxLon':"117",\
              'fcstEle':"TEM",'levelType':"100",\
              'fcstLevel':"850"}
    
    # 2.4 返回文件的格式 
    dataFormat = "xml"
    
    # 3. 调用接口
    result = client.callAPI_to_serializedStr(userId, pwd, interfaceId, params, dataFormat)
    
    # 4. 输出接口
    print (result)