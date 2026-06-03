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
        
    # 2.2  接口ID(删除站点、指数等数据)  
    interfaceId = "saveStationData"    
        
    # 2.3  接口参数，多个参数间无顺序     
    # 必选参数    (1)资料代码：城镇天气预报产品要素资料(测试);(2)要素字段代码（键值）)。
    params = {'dataCode':"SEVP_WEFC_ACPP_STORE",\
              'Elements':"Datetime,Station_Id_C,Year,Mon,Day,Hour,Validtime,WIN_D,WIN_Turn,WINF,WINF_Turn,TEM_Max_2m,TEM_Min_2m"}
    
    # 2.4 写入要素序列化数据值，字段之间用逗号（,）分隔，行之间用分号(;)分开,前面的为key要素的值，后面为value要素的值
    inString = "20160326060000,54323,2016,3,26,6,72,5,5,0,0,2.0000,-50.0000;20160327060000,54324,2016,3,27,6,96,4,4,1,1,2.0000,-50.0000"

    # 3. 调用接口 
    result = client.callAPI_to_storeSerializedStr(userId, pwd, interfaceId, params, inString)
    # 4. 输出结果
    print (result)