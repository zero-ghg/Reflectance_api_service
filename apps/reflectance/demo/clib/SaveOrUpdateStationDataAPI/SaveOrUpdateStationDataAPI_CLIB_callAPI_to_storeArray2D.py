# coding=utf8
'''
Modified in 2016/03/28
@author: xjunior
'''
from cma.music.DataStoreClient import DataStoreClient
if __name__ == "__main__":
    
    # 1. 定义client对象  
    client = DataStoreClient()
    
    #2. 调用方法的参数定义，并赋值
    # 2.1 用户名&密码 
    userId = "NMIC_XTS_CMADAASTEST" 
    pwd = "test1234" 
        
    # 2.2  接口ID(保存或更新站点、指数等数据)  
    interfaceId = "saveOrUpdateStationData"    
        
    # 2.3  接口参数，多个参数间无顺序     
    # 必选参数    (1)资料代码：城镇天气预报产品要素资料(测试);(2)要素条件要素;(3)要素字段代码（键值）)。
    params = {'dataCode':"SEVP_WEFC_ACPP_STORE",\
              'valueEles':"Year,Mon,Day,Hour,Validtime,WIN_D,WIN_Turn,WINF,WINF_Turn,TEM_Max_2m,TEM_Min_2m",\
              'KeyEles':"Datetime,Station_Id_C"}
    
    # 2.4 插入或更新以下记录(inArray2D为python的二维字符数组例子)
    inArray2D = [
                ['20160306060000', '54323', '2016','3', '6', '6', '168', '7','7', '1','1', '0.0000','-50.0000'],\
                ['20160307060000', '54324', '2016','3', '7', '6', '24', '1','1', '1','1', '-50.0000','-50.0000'],\
                ['20160308060000', '54324', '2016','3', '8', '6', '48', '8','8', '1','1', '-50.0000','-50.0000'],\
                ['20160314060000', '54326', '2016','3', '14', '6', '72', '5','5', '0','0', '2.0000','-50.0000'],\
                ['20160315060000', '54326', '2016','3', '15', '6', '144', '7','7', '0','0', '4.0000','-50.0000']
                ]
    
    # 3. 调用接口 
    result = client.callAPI_to_storeArray2D(userId, pwd, interfaceId,params,inArray2D)

    # 4. 输出结果
    print (result)