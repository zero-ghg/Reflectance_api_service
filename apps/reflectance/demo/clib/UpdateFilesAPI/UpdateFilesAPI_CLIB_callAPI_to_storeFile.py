# coding=utf8
'''
Modified in 2016/05/06
@author: nixl
'''
from cma.music.DataStoreClient import DataStoreClient
if __name__ == "__main__":
    
    # 1. 定义client对象  
    client = DataStoreClient()
    
    #2. 调用方法的参数定义，并赋值
    # 2.1 用户名&密码 
    userId = "NMIC_XTS_CMADAASTEST" 
    pwd = "test1234" 
        
    # 2.2  接口ID
    interfaceId = "updateFiles"    
        
    # 2.3  接口参数，多个参数间无顺序     
    # 必选参数    (1)资料代码(2)要素字段代码（键值）)。
    params = {'dataCode':"SEVP_CIPAS_TEM_ANOM",\
              'valueEles':"PUBLISH_TIME,AREA",\
              'keyEles':"Datetime"}
    
    # 2.4 要素值信息
    inArray2D = [["20151111000000", "20151114120000","NHE"],\
                 ["20151113000000", "20151113000000","NHE"]]
    
    ftpfiles =["D:\Project\workspace\music-demo-python\cipas\MOP_CHCC_NCEPRA_WMFS_TMP_NH_0_PM_20151111_0000.png","D:\Project\workspace\music-demo-python\cipas\MOP_CHCC_NCEPRA_WMFS_TMP_NH_0_PM_20151113_0000.png"];
    # 3. 调用接口 
    result = client.callAPI_to_storeFile(userId, pwd, interfaceId,params,inArray2D,ftpfiles)

    # 4. 输出结果
    print (result)