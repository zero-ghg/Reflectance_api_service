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
    interfaceId = "statSurfEle"
        
    # 2.3  接口参数，多个参数间无顺序     
    # 必选参数    (1)资料：中国地面逐小时资料;(2)统计分组：站号，站名 ;
    #        (3)统计要素：总降水，平均降水，总气温，平均气温; (4)时间范围，前开后闭; 
    # 可选参数   (5)排序：按照累计降水从大到小;
    #        (6)台站级别：国家站（基准站、基本站、一般站）;(6)返回最多记录数：10。
    params = {'dataCode':"SURF_CHN_MUL_HOR",\
              'elements':"Station_ID_C,Station_Name",\
              'statEles':"SUM_PRE_1h,AVG_PRE_1h,SUM_TEM,AVG_TEM",\
              'timeRange':"(20190601000000,20190601060000]",\
              'orderby':"SUM_PRE_1h:desc",\
              #'staLevels':"011,012,013",\
              'limitCnt':"10"
              }
    
    # 2.4 返回文件的格式 
    dataFormat = "json"
    
    # 3. 调用接口
    result = client.callAPI_to_serializedStr(userId, pwd, interfaceId, params, dataFormat)
    
    # 4. 输出接口
    print (result)