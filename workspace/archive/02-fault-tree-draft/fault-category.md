实例部署	部署KVCache worker实例	验证各类故障对KVCache worker实例部署时影响	容器故障-内存不足
			容器故障-CPU过载
			容器故障-存储空间不足
			ETCD故障-集群不可用
			ETCD故障-主节点故障
			ETCD故障-网络中断
			服务器故障-内存故障
			TCP网卡故障-全部网卡down
			TCP网卡故障-单网卡down
			TCP网卡故障-时延
			TCP网卡故障-丢包
			TCP网卡故障-抖动
			TCP网卡故障-闪断
			TCP网卡故障-带宽不足
	"部署业务实例
(涉及KVCache Init 接口)"	验证各类故障对业务实例部署时通过TCP与同节点KVCache worker建共享内存通道的影响	KVCache worker故障-进程退出
			KVCache worker故障-进程反复重启
			KVCache worker故障-进程挂死
			容器故障-Worker容器重启
			容器故障-内存不足
			容器故障-CPU过载
			容器故障-存储空间不足
			ETCD故障-集群不可用
			ETCD故障-主节点故障
			ETCD故障-网络中断
			服务器故障-内存故障
			TCP网卡故障-全部网卡down
			TCP网卡故障-单网卡down
			TCP网卡故障-时延
			TCP网卡故障-丢包
			TCP网卡故障-抖动
			TCP网卡故障-闪断
			TCP网卡故障-带宽不足
		验证各类故障对业务实例部署时通过TCP与远端节点KVCache worker建UB通道的影响	KVCache worker故障-进程退出
			KVCache worker故障-进程反复重启
			KVCache worker故障-进程挂死
			OS故障-重启
			OS故障-Panic
			OS故障-硬盘IO速度慢
			容器故障-内存不足
			容器故障-CPU过载
			容器故障-存储空间不足
			UB管控面故障-UBSE进程故障
			UB管控面故障-UBM进程故障
			ETCD故障-集群不可用
			ETCD故障-主节点故障
			ETCD故障-网络中断
分布式读、写、查	"业务实例写KVCache数据
(涉及KVCache Set接口)"	验证各类故障对业务实例通过共享内存写数据到同节点KVCache worker流程的影响	SDK故障-进程异常退出
			SDK故障-进程反复重启
			SDK故障-进程挂死
			KVCache worker故障-进程退出
			KVCache worker故障-进程反复重启
			KVCache worker故障-进程挂死
			OS故障-重启
			OS故障-Panic
			OS故障-硬盘IO速度慢
			容器故障-SDK容器重启
			容器故障-Worker容器重启
			容器故障-内存不足
			容器故障-CPU过载
			容器故障-存储空间不足
			分布式网盘故障-读写慢
			分布式网盘故障-网络中断
			分布式网盘故障-网络时延
			分布式网盘故障-网络抖动
			分布式网盘故障-网络丢包
			服务器故障-BMC强制上下电
			服务器故障-内存故障
			TCP网卡故障-全部网卡down
			TCP网卡故障-单网卡down
			TCP网卡故障-时延
			TCP网卡故障-丢包
			TCP网卡故障-抖动
			TCP网卡故障-闪断
			TCP网卡故障-带宽不足
		验证各类故障对业务实例通过UB写数据到远端节点KVCache worker流程的影响	SDK故障-进程异常退出
			SDK故障-进程反复重启
			SDK故障-进程挂死
			KVCache worker故障-进程退出
			KVCache worker故障-进程反复重启
			KVCache worker故障-进程挂死
			OS故障-重启
			OS故障-Panic
			OS故障-硬盘IO速度慢
			容器故障-SDK容器重启
			容器故障-Worker容器重启
			容器故障-内存不足
			容器故障-CPU过载
			容器故障-存储空间不足
			UB管控面故障-UBSE进程故障
			UB管控面故障-UBM进程故障
			分布式网盘故障-读写慢
			分布式网盘故障-网络中断
			分布式网盘故障-网络时延
			分布式网盘故障-网络抖动
			分布式网盘故障-网络丢包
			服务器故障-BMC强制上下电
			服务器故障-内存故障
			UB端口故障-down
			UB端口故障-闪断
			UB端口故障-丢包
			UB端口故障-降lane
			UB芯片故障-Jetty不足
			UB芯片故障-UB带宽不足
			UB芯片故障-CE故障
			UB芯片故障-NFE故障
			UB芯片故障-FE故障
			TCP网卡故障-全部网卡down
			TCP网卡故障-单网卡down
			TCP网卡故障-时延
			TCP网卡故障-丢包
			TCP网卡故障-抖动
			TCP网卡故障-闪断
			TCP网卡故障-带宽不足
			L1交换机故障-端口故障
			L1交换机故障-端口闪断
			L1交换机故障-端口降lane
			L1交换机故障-整机故障
			L2交换机故障-端口故障
			L2交换机故障-端口闪断
			L2交换机故障-端口降lane
			L2交换机故障-整机故障
	"业务实例读KVCache数据
（涉及 KVCache Get接口）"	验证各类故障对业务实例本节点缓存命中，通过共享内存从同节点KVCache worker读数据流程的影响	SDK故障-进程异常退出
			SDK故障-进程反复重启
			SDK故障-进程挂死
			KVCache worker故障-进程退出
			KVCache worker故障-进程反复重启
			KVCache worker故障-进程挂死
			OS故障-重启
			OS故障-Panic
			OS故障-硬盘IO速度慢
			容器故障-SDK容器重启
			容器故障-Worker容器重启
			容器故障-内存不足
			容器故障-CPU过载
			容器故障-存储空间不足
			服务器故障-BMC强制上下电
			服务器故障-内存故障
			TCP网卡故障-全部网卡down
			TCP网卡故障-单网卡down
			TCP网卡故障-时延
			TCP网卡故障-丢包
			TCP网卡故障-抖动
			TCP网卡故障-闪断
			TCP网卡故障-带宽不足
		验证各类故障对业务实例远端节点缓存命中，同节点KVCache worker通过UB通道连接远端节点worker读数据流程的影响	SDK故障-进程异常退出
			SDK故障-进程反复重启
			SDK故障-进程挂死
			KVCache worker故障-进程退出
			KVCache worker故障-进程反复重启
			KVCache worker故障-进程挂死
			OS故障-重启
			OS故障-Panic
			OS故障-硬盘IO速度慢
			容器故障-SDK容器重启
			容器故障-Worker容器重启
			容器故障-内存不足
			容器故障-CPU过载
			容器故障-存储空间不足
			UB管控面故障-UBSE进程故障
			UB管控面故障-UBM进程故障
			服务器故障-BMC强制上下电
			服务器故障-内存故障
			UB端口故障-down
			UB端口故障-闪断
			UB端口故障-丢包
			UB端口故障-降lane
			UB芯片故障-Jetty不足
			UB芯片故障-UB带宽不足
			UB芯片故障-CE故障
			UB芯片故障-NFE故障
			UB芯片故障-FE故障
			TCP网卡故障-全部网卡down
			TCP网卡故障-单网卡down
			TCP网卡故障-时延
			TCP网卡故障-丢包
			TCP网卡故障-抖动
			TCP网卡故障-闪断
			TCP网卡故障-带宽不足
			L1交换机故障-端口故障
			L1交换机故障-端口闪断
			L1交换机故障-端口降lane
			L1交换机故障-整机故障
			L2交换机故障-端口故障
			L2交换机故障-端口闪断
			L2交换机故障-端口降lane
			L2交换机故障-整机故障
		验证各类故障对业务实例远端节点缓存命中，业务实例直接通过UB通道连接远端节点worker读数据流程的影响	SDK故障-进程异常退出
			SDK故障-进程反复重启
			SDK故障-进程挂死
			KVCache worker故障-进程退出
			KVCache worker故障-进程反复重启
			KVCache worker故障-进程挂死
			OS故障-重启
			OS故障-Panic
			OS故障-硬盘IO速度慢
			容器故障-SDK容器重启
			容器故障-Worker容器重启
			容器故障-内存不足
			容器故障-CPU过载
			容器故障-存储空间不足
			UB管控面故障-UBSE进程故障
			UB管控面故障-UBM进程故障
			服务器故障-BMC强制上下电
			服务器故障-内存故障
			UB端口故障-down
			UB端口故障-闪断
			UB端口故障-丢包
			UB端口故障-降lane
			UB芯片故障-Jetty不足
			UB芯片故障-UB带宽不足
			UB芯片故障-CE故障
			UB芯片故障-NFE故障
			UB芯片故障-FE故障
			TCP网卡故障-全部网卡down
			TCP网卡故障-单网卡down
			TCP网卡故障-时延
			TCP网卡故障-丢包
			TCP网卡故障-抖动
			TCP网卡故障-闪断
			TCP网卡故障-带宽不足
			L1交换机故障-端口故障
			L1交换机故障-端口闪断
			L1交换机故障-端口降lane
			L1交换机故障-整机故障
			L2交换机故障-端口故障
			L2交换机故障-端口闪断
			L2交换机故障-端口降lane
			L2交换机故障-整机故障
	"业务实例查KVCache数据是否存在
（涉及KVCache Exist接口）"	验证各类故障对业务实例通过TCP连接同/远端节点KVCache worker查询数据是否存在流程的影响	SDK故障-进程异常退出
			SDK故障-进程反复重启
			SDK故障-进程挂死
			KVCache worker故障-进程退出
			KVCache worker故障-进程反复重启
			KVCache worker故障-进程挂死
			OS故障-重启
			OS故障-Panic
			OS故障-硬盘IO速度慢
			容器故障-SDK容器重启
			容器故障-Worker容器重启
			容器故障-内存不足
			容器故障-CPU过载
			容器故障-存储空间不足
			服务器故障-BMC强制上下电
			TCP网卡故障-全部网卡down
			TCP网卡故障-单网卡down
			TCP网卡故障-时延
			TCP网卡故障-丢包
			TCP网卡故障-抖动
			TCP网卡故障-闪断
			TCP网卡故障-带宽不足
扩容、缩容	业务实例扩容	验证各类故障对业务实例扩容期间KVCache SDK与worker通过TCP建链共享内存通道/UB通道的影响	KVCache worker故障-进程退出
			KVCache worker故障-进程反复重启
			KVCache worker故障-进程挂死
			容器故障-Worker容器重启
			容器故障-内存不足
			容器故障-CPU过载
			容器故障-存储空间不足
			ETCD故障-集群不可用
			ETCD故障-主节点故障
			ETCD故障-网络中断
			服务器故障-BMC强制上下电
			服务器故障-内存故障
			TCP网卡故障-全部网卡down
			TCP网卡故障-单网卡down
			TCP网卡故障-时延
			TCP网卡故障-丢包
			TCP网卡故障-抖动
			TCP网卡故障-闪断
			TCP网卡故障-带宽不足
	业务实例缩容	验证各类故障对业务实例缩容期间共享内存释放及woker连接的影响	KVCache worker故障-进程退出
			KVCache worker故障-进程反复重启
			KVCache worker故障-进程挂死
			容器故障-Worker容器重启
			容器故障-内存不足
			容器故障-CPU过载
			容器故障-存储空间不足
			服务器故障-BMC强制上下电
			服务器故障-内存故障
			TCP网卡故障-全部网卡down
			TCP网卡故障-单网卡down
			TCP网卡故障-时延
			TCP网卡故障-丢包
			TCP网卡故障-抖动
			TCP网卡故障-闪断
			TCP网卡故障-带宽不足
	KVCache worker实例扩容	验证各类故障对KVCache worker实例扩容元数据迁移的影响	OS故障-重启
			OS故障-Panic
			OS故障-硬盘IO速度慢
			容器故障-Worker容器重启
			容器故障-内存不足
			容器故障-CPU过载
			容器故障-存储空间不足
			ETCD故障-集群不可用
			ETCD故障-主节点故障
			ETCD故障-网络中断
			服务器故障-BMC强制上下电
			服务器故障-内存故障
			TCP网卡故障-全部网卡down
			TCP网卡故障-单网卡down
			TCP网卡故障-时延
			TCP网卡故障-丢包
			TCP网卡故障-抖动
			TCP网卡故障-闪断
			TCP网卡故障-带宽不足
	KVCache worker实例缩容	验证各类故障对KVCache worker实例缩容数据迁移和SDK切换的影响	SDK故障-进程异常退出
			SDK故障-进程反复重启
			SDK故障-进程挂死
			OS故障-重启
			OS故障-Panic
			OS故障-硬盘IO速度慢
			容器故障-SDK容器重启
			容器故障-Worker容器重启
			容器故障-内存不足
			容器故障-CPU过载
			容器故障-存储空间不足
			UB管控面故障-UBSE进程故障
			UB管控面故障-UBM进程故障
			ETCD故障-集群不可用
			ETCD故障-主节点故障
			ETCD故障-网络中断
			分布式网盘故障-读写慢
			分布式网盘故障-网络中断
			分布式网盘故障-网络时延
			分布式网盘故障-网络抖动
			分布式网盘故障-网络丢包
			服务器故障-BMC强制上下电
			服务器故障-内存故障
			UB端口故障-down
			UB端口故障-闪断
			UB端口故障-丢包
			UB端口故障-降lane
			UB芯片故障-Jetty不足
			UB芯片故障-UB带宽不足
			UB芯片故障-CE故障
			UB芯片故障-NFE故障
			UB芯片故障-FE故障
			TCP网卡故障-全部网卡down
			TCP网卡故障-单网卡down
			TCP网卡故障-时延
			TCP网卡故障-丢包
			TCP网卡故障-抖动
			TCP网卡故障-闪断
			TCP网卡故障-带宽不足
			L1交换机故障-端口故障
			L1交换机故障-端口闪断
			L1交换机故障-端口降lane
			L1交换机故障-整机故障
			L2交换机故障-端口故障
			L2交换机故障-端口闪断
			L2交换机故障-端口降lane
			L2交换机故障-整机故障
实例升级	KVCache worker实例升级	验证各类故障对KVCache worker实例升级数据迁移和SDK切换的影响	SDK故障-进程异常退出
			SDK故障-进程反复重启
			SDK故障-进程挂死
			OS故障-重启
			OS故障-Panic
			OS故障-硬盘IO速度慢
			容器故障-SDK容器重启
			容器故障-Worker容器重启
			容器故障-内存不足
			容器故障-CPU过载
			容器故障-存储空间不足
			UB管控面故障-UBSE进程故障
			UB管控面故障-UBM进程故障
			ETCD故障-集群不可用
			ETCD故障-主节点故障
			ETCD故障-网络中断
			分布式网盘故障-读写慢
			分布式网盘故障-网络中断
			分布式网盘故障-网络时延
			分布式网盘故障-网络抖动
			分布式网盘故障-网络丢包
			服务器故障-BMC强制上下电
			服务器故障-内存故障
			UB端口故障-down
			UB端口故障-闪断
			UB端口故障-丢包
			UB端口故障-降lane
			UB芯片故障-Jetty不足
			UB芯片故障-UB带宽不足
			UB芯片故障-CE故障
			UB芯片故障-NFE故障
			UB芯片故障-FE故障
			TCP网卡故障-全部网卡down
			TCP网卡故障-单网卡down
			TCP网卡故障-时延
			TCP网卡故障-丢包
			TCP网卡故障-抖动
			TCP网卡故障-闪断
			TCP网卡故障-带宽不足
	业务实例升级	验证各类故障对业务实例升级过程中SDK与同节点/远端节点KVCache worker重新建链的影响	KVCache worker故障-进程退出
			KVCache worker故障-进程反复重启
			KVCache worker故障-进程挂死
			容器故障-Worker容器重启
			容器故障-内存不足
			容器故障-CPU过载
			容器故障-存储空间不足
			ETCD故障-集群不可用
			ETCD故障-主节点故障
			ETCD故障-网络中断
			服务器故障-BMC强制上下电
			服务器故障-内存故障
			TCP网卡故障-全部网卡down
			TCP网卡故障-单网卡down
			TCP网卡故障-时延
			TCP网卡故障-丢包
			TCP网卡故障-抖动
			TCP网卡故障-闪断
			TCP网卡故障-带宽不足