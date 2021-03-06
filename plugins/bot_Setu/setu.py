# -*- coding: utf-8 -*-
# @Time    : 2021/6/20 20:59
# @Author  : yuban10703


import time
from loguru import logger
from .dataBase import getGroupConfig, getFriendConfig
from .model import GetSetuConfig, GroupConfig, FriendConfig, FinishSetuData
from .dataBase import ifSent, freqLimit
from typing import Union, List
from botoy import S
from .APIS import Lolicon, Yuban, Pixiv
from botoy import GroupMsg, FriendMsg


class Setu:
    def __init__(self, ctx: Union[GroupMsg, FriendMsg], getSetuConfig: GetSetuConfig):
        """
        用正则提取要获取的色图数量,标签,是否R18等信息
        :param ctx: 消息信息
        """
        self.ctx = ctx
        self.send = S.bind(self.ctx)
        self.getSetuConfig = getSetuConfig
        # 要获取色图的信息(数量,tag......)
        if self.ctx.type in ['temp', 'group']:  # 群聊或者群临时会话就加载该群的配置文件
            # getSetuConfig.flagID = self.ctx.QQG
            self.config: GroupConfig = getGroupConfig(self.ctx.QQG)
        else:
            # getSetuConfig.flagID = self.ctx.QQ
            self.config: FriendConfig = getFriendConfig()
            # self.config = None

    def buildMsg(self, setudata: FinishSetuData):
        msgDict = {
            'title': '标题:{}'.format(setudata.title),
            'picID': '作品id:{}'.format(setudata.picID),
            'picWebUrl': setudata.picWebUrl,
            'page': 'page:{}'.format(setudata.page),
            'author': '作者:{}'.format(setudata.author),
            'authorID': '作者id:{}'.format(setudata.authorID),
            'authorWebUrl': setudata.authorWebUrl,
            'picOriginalUrl': '原图:{}'.format(setudata.picOriginalUrl_Msg),
            'tags': 'Tags:[{}]'.format(setudata.tags),
        }
        msg = ''
        # if self.config:  # 群聊和临时

        if self.ctx.type == 'friend':  # 好友会话
            for v in msgDict.values():
                msg += (('' if msg == '' else '\r\n') + v)
            return msg
        else:
            for k, v in self.config.setuInfoShow.dict().items():
                if v:
                    msg += (('' if msg == '' else '\r\n') + msgDict[k])
            if self.config.setting.revokeTime.dict()[self.ctx.type] != 0:
                msg += '\r\nREVOKE[{}]'.format(self.config.setting.revokeTime.dict()[self.ctx.type])
            if self.config.setting.at:
                return '\r\n' + msg
            return msg

    def get(self):
        """
        遍历每个API
        :return:
        """
        conversion_dict = {
            'Lolicon': 'lolicon',
            'Yuban': 'yuban',
            'Pixiv': 'pixiv'
        }

        for API in [Lolicon, Yuban, Pixiv]:
            if self.config.setting.api.dict()[conversion_dict[API.__name__]]:  # 遍历API的开启状态
                setu_all = API(self.getSetuConfig).main()
                setu_filtered = self.filter_Sent(setu_all)
                logger.success(
                    '{}:{} 从API:{}获取到关于{}的色图{}张,去除{}s内重复发送过的后剩余{}张'.format(
                        '好友' if self.ctx.type == 'friend' else '群',
                        self.ctx.QQ if self.ctx.type == 'friend' else self.ctx.QQG,
                        API.__name__, self.getSetuConfig.tags,
                        len(setu_all),
                        self.config.setting.sentRefreshTime,
                        len(setu_filtered))
                )
                self.getSetuConfig.doneNum += len(setu_filtered)  # 记录获取到的数量
                self.sendsetu(setu_filtered)

        if self.getSetuConfig.doneNum == 0:  # 遍历完API一张都没获取到
            self.send.text(self.config.replyMsg.notFound)
            return
        if self.getSetuConfig.doneNum < self.getSetuConfig.toGetNum:  # 获取到的数量小于预期
            self.send.text(
                self.config.replyMsg.insufficient.format(tag=self.getSetuConfig.tags, num=self.getSetuConfig.doneNum))
            return

    def sendsetu(self, setus: List[FinishSetuData]):
        """发送setu"""
        conversion_dict = {
            'original': 'picOriginalUrl',
            'large': 'picLargeUrl',
            'medium': 'picMediumUrl'
        }
        for setu in setus:
            # print(self.buildMsg(setu))
            self.send.image(setu.dict()[conversion_dict[self.config.setting.quality]],
                            self.buildMsg(setu),
                            self.config.setting.at)

    def auth(self) -> bool:
        """
        检查群是否开启setu,r18功能
        :return:
        """
        if not self.config.setting.setu.dict()[self.ctx.type]:
            self.send.text(self.config.replyMsg.closed)
            return False
        if not self.config.setting.r18.dict()[self.ctx.type] and self.getSetuConfig.level > 0:
            self.send.text(self.config.replyMsg.noR18)
            return False

        return True

    def check_parameters(self) -> bool:
        """
        检查数量
        :return:
        """
        if self.getSetuConfig.toGetNum > self.config.setting.singleMaximum.dict()[self.ctx.type]:
            self.send.text(self.config.replyMsg.tooMuch)
            return False
        if self.getSetuConfig.toGetNum <= 0:
            self.send.text(self.config.replyMsg.tooSmall)
            return False
        if self.config.setting.r18.dict()[self.ctx.type] and self.getSetuConfig.level != 1:  # 群开启了R18,则在非指定r18时返回混合内容
            self.getSetuConfig.level = 2
        return True

    def filter_Sent(self, setus: List[FinishSetuData]) -> List[FinishSetuData]:  # 过滤一段时间内发送过的图片
        if setus != None:
            setus_copy = setus.copy()
            for setu in setus_copy:
                if ifSent(self.ctx.QQG if self.ctx.type in ['temp', 'group'] else self.ctx.QQ, int(setu.picID),
                          self.config.setting.sentRefreshTime):
                    setus_copy.remove(setu)
            return setus_copy
        return []

    def group_or_temp(self):
        """
        群和临时消息
        :return:
        """
        if not self.auth():  # 鉴权
            return
        if not self.check_parameters():  # 检查数量
            return
        if data := freqLimit(self.ctx.QQG, self.config, self.getSetuConfig):  # 触发频率限制
            freqConfig = data[0]
            data_tmp = data[1]
            self.send.text(self.config.replyMsg.freqLimit.format(
                time=freqConfig.refreshTime,
                limitCount=freqConfig.limitCount,
                callDone=data_tmp['callDone'],
                r_time=int(freqConfig.refreshTime - (time.time() - data_tmp['time'])))
            )
            return
        self.get()

    def friend(self):
        """
        好友消息
        :return:
        """
        if not self.config.setting.setu:
            self.send.text(self.config.replyMsg.closed)
            return
        if not self.config.setting.r18 and self.getSetuConfig.level > 0:
            self.send.text(self.config.replyMsg.noR18)
            return
        if self.getSetuConfig.toGetNum > self.config.setting.singleMaximum:
            self.send.text(self.config.replyMsg.tooMuch)
            return
        if self.getSetuConfig.toGetNum <= 0:
            self.send.text(self.config.replyMsg.tooSmall)
            return
        if self.config.setting.r18 and self.getSetuConfig.level != 1:  # 群开启了R18,则在非指定r18时返回混合内容
            self.getSetuConfig.level = 2
        self.get()

    def main(self):
        """群聊和临时会话一起处理
        好友私聊单独处理"""
        if self.ctx.type == 'friend':  # 好友会话
            self.friend()
        else:  # 群聊or临时会话
            if self.config:  # 如果有群配置文件
                self.group_or_temp()
            else:
                logger.warning('无群:{}的配置文件'.format(self.ctx.QQG))
                self.send.text('如果要使用Setu插件,请参考https://github.com/opq-osc/OPQ-SetuBot/wiki对本群的配置文件初始化')
                return
