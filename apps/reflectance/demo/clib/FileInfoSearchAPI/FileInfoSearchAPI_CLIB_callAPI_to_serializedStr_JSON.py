# coding=utf8
'''
Modified in 2016/03/28
@author: xjunior
'''
from cma.music.DataQueryClient import DataQueryClient
if __name__ == "__main__":

    # 1. 定义client对象  
    client = DataQueryClient()
    
    # 2. 调用方法的参数定义，并赋值
    # 2.1 用户名&密码 
    userId = "NMIC_XTS_CMADAASTEST" 
    pwd = "test1234" 
        
    # 2.2  接口ID     
    interfaceId = "getRadaFileByTimeRangeAndStaId"    
        
    # 2.3  接口参数，多个参数间无顺序     
    # 必选参数    (1)资料：质控前原始格式多普勒雷达基数据;(2)时间段，前闭后开;(3)雷达站。
    params = {'dataCode':"RADA_L2_UFMT",\
              'timeRange':"[20190601000000,20190601000600)",\
              'staIds':"Z9859,Z9852,Z9856,Z9851,Z9855"}
    
    # 可选参数
    # 2.4 返回文件的格式
    dataFormat = "json"
    
    # 3. 调用接口
    result = client.callAPI_to_serializedStr(userId, pwd, interfaceId,params, dataFormat) 
    
    # 4. 输出结果
    print (result)