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
    interfaceId = "getStaInfoInRect"
        
    # 2.3  接口参数，多个参数间无顺序     
    # 必选参数    (1)资料代码：中国地名台站信息; (2)检索要素：站号、站名、小时降水、气压、相对湿度、能见度、2分钟平均风速、2分钟风向; 
    #          (3)经纬度范围：北京及周边（纬度39-42，经度115-117）
    params = {'dataCode':"STA_INFO_SURF_CHN",\
              'elements':"Station_ID_C,Station_Name,Lat,Lon,Alti",\
              'minLat':"39",'maxLat':"42",'minLon':"115",'maxLon':"117"}
    
    # 2.4 返回文件的格式 
    dataFormat = "html"
    
    # 2.5 文件的本地全路径 
    savePath = "F:/temp/data.html"
    
    # 3. 调用接口
    result = client.callAPI_to_saveAsFile(userId, pwd, interfaceId, params, dataFormat, savePath)
    
    # 4. 输出接口
    print (result.request)
    print (result.fileInfos)