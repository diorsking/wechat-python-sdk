# -*- coding: utf-8 -*-

import hashlib
import requests
import time
import json
import cgi
import random

from WXBizMsgCrypt import WXBizMsgCrypt

from .corp_message import MESSAGE_TYPES, UnknownMessage
from .exceptions import ParseError, NeedParseError, NeedParamError, OfficialAPIError, CorpSignatureError
from .lib import XMLStore
from .corp_reply import TextReply

class WechatCorp(object):
    """
    微信企业号基本功能类

    """
    def __init__(self, CorpID=None, Secret=None, access_token=None, access_token_expires_at=None, Token=None, EncodingAESKey=None,):

        """
        :param CorpID: CorpID
        :param Secret: Corp Secret
        :param access_token: 直接导入的 access_token 值, 该值需要在上一次该类实例化之后手动进行缓存并在此处传入, 如果不传入, 将会在需要时自动重新获取
        :param access_token_expires_at: 直接导入的 access_token 的过期日期，该值需要在上一次该类实例化之后手动进行缓存并在此处传入, 如果不传入, 将会在需要时自动重新获取
        """

        self.__corpid=CorpID
        self.__secret=Secret
        self.__token=Token
        self.__EncodingAESKey=EncodingAESKey

        self.__access_token = access_token
        self.__access_token_expires_at = access_token_expires_at
        self.__wxcpt=WXBizMsgCrypt(self.__token,self.__EncodingAESKey,self.__corpid)

    def grant_token(self,override=True):
        """
        获取 Access Token
        详情请参考 http://qydev.weixin.qq.com/wiki/index.php?title=%E4%B8%BB%E5%8A%A8%E8%B0%83%E7%94%A8
        :param override: 是否在获取的同时覆盖已有 access_token (默认为True)
        :return: 返回的 JSON 数据包
        :raise HTTPError: 微信api http 请求失败
        """
        self._check_corpid_secret()
        response_json = self._get(
            url="https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={
                "corpid": self.__corpid,
                "corpsecret": self.__secret,
            }
        )
        if override:
            self.__access_token = response_json['access_token']
            self.__access_token_expires_at = int(time.time()) + response_json['expires_in']
        return response_json

    def get_access_token(self):
        """
        获取 Access Token 及 Access Token 过期日期, 仅供缓存使用, 如果希望得到原生的 Access Token 请求数据请使用 :func:`grant_token`
        :return: dict 对象, key 包括 `access_token` 及 `access_token_expires_at`
        """
        self._check_corpid_secret()

        return {
            'access_token': self.access_token,
            'access_token_expires_at': self.__access_token_expires_at,
        }

    def url_verify(self, msg_signature, timestamp, nonce, echostr):
        """
        回调URL信息验证
        详情请参考 http://qydev.weixin.qq.com/wiki/index.php?title=%E5%9B%9E%E8%B0%83%E6%A8%A1%E5%BC%8F
        :param msg_signature: 微信加密签名
        :param timestamp: 时间戳
        :param nonce: 随机数
        :param echostr: 加密的随机字符串
        :return: 验证URL成功，将sEchoStr返回给企业号
        """
        self._check_token_EncodingAESKey()

        if not msg_signature or not timestamp or not nonce or not echostr:
            raise CorpSignatureError('Please provide msg_signature and timestamp and nonce and echostr parameter in the construction of class.')

        ret,sEchoStr=self.__wxcpt.verify_url(msg_signature, timestamp, nonce, echostr)
        if(ret!=0):
            raise CorpSignatureError("ERR: VerifyURL ret: " + ret)
        else:
            return sEchoStr

    def parse_data(self, msg_signature, timestamp, nonce, data):
        """
        解析微信服务器发送过来的数据并保存类中
        1.解析出url上的参数，包括消息体签名(msg_signature)，时间戳(timestamp)以及随机数字串(nonce)
	    2.验证消息体签名的正确性。
	    3.将post请求的数据进行xml解析，并将<Encrypt>标签的内容进行解密，解密出来的明文即是用户回复消息的明文，明文格式请参考官方文档
        :param data: HTTP Request 的 Body 数据
        :raises ParseError: 解析微信服务器数据错误, 数据不合法
        """
        result = {}
        if type(data) == unicode:
            data = data.encode('utf-8')
        elif type(data) == str:
            pass
        else:
            raise ParseError()

        #解密数据
        ret,sMsg=self.__wxcpt.decrypt_message(data, msg_signature, timestamp, nonce)

        try:
            xml = XMLStore(xmlstring=sMsg)
        except Exception:
            raise ParseError()

        result = xml.xml2dict
        result['raw'] = sMsg
        result['type'] = result.pop('MsgType').lower()

        message_type = MESSAGE_TYPES.get(result['type'], UnknownMessage)
        self.__message = message_type(result)
        self.__is_parse = True

    @property
    def message(self):
        return self.get_message()

    def get_message(self):
        """
        获取解析好的 CorpMessage 对象
        :return: 解析好的 CorpMessage 对象
        """
        self._check_parse()
        return self.__message

    def response_text(self, content, escape=False):
        """
        将文字信息 content 组装为符合微信服务器要求的响应数据
        :param content: 回复文字
        :param escape: 是否转义该文本内容 (默认不转义)
        :return: 符合微信服务器要求的 XML 响应数据
        """
        self._check_parse()
        content = self._transcoding(content)
        if escape:
            content = cgi.escape(content)

        response_xml= TextReply(message=self.__message, content=content).render()
        return self._EncryptMsg(response_xml)

    @property
    def wxcpt(self):
        """
        :return:
        """
        return self.__wxcpt

    def _EncryptMsg(self,response_xml):
        """
        返回加密的xml信息，格式
        <xml>
            <Encrypt><![CDATA[     ]]></Encrypt>
            <MsgSignature><![CDATA[      ]]></MsgSignature>
            <TimeStamp>1433678396</TimeStamp>
            <Nonce><![CDATA[1372623149]]></Nonce>
        </xml>
        :param response_xml: 需要加密的xml数据
        :return:
        """
        sReqTimeStamp=str(int(time.time()))
        sReqNonce="".join(map(lambda x:str(random.randint(1,9)),range(16)))
        ret,sEncryptMsg = self.__wxcpt.encrypt_message(response_xml.encode("utf-8"),sReqNonce,sReqTimeStamp)
        return sEncryptMsg

    @property
    def access_token(self):
        self._check_corpid_secret()

        if self.__access_token:
            now = time.time()
            if self.__access_token_expires_at - now > 60:
                return self.__access_token
        self.grant_token()
        return self.__access_token

    def _check_corpid_secret(self):
        """
        检查 CorpID, Corp Secret 是否存在
        :raises NeedParamError: Token 参数没有在初始化的时候提供
        """
        if not self.__corpid or not self.__secret:
            raise NeedParamError('Please provide CorpID and Secret parameters in the construction of class.')

    def _check_token_EncodingAESKey(self):
        """
        检查 Token, EncodingAESKey 是否存在
        :raises NeedParamError: Token 参数没有在初始化的时候提供
        """
        if not self.__token or not self.__EncodingAESKey:
            raise NeedParamError('Please provide Token and EncodingAESKey parameter in the construction of class.')


    def _check_parse(self):
        """
        检查是否成功解析微信服务器传来的数据
        :raises NeedParseError: 需要解析微信服务器传来的数据
        """
        if not self.__is_parse:
            raise NeedParseError()

    def _check_official_error(self, json_data):
        """
        检测微信公众平台返回值中是否包含错误的返回码
        :raises OfficialAPIError: 如果返回码提示有错误，抛出异常；否则返回 True
        """
        if "errcode" in json_data and json_data["errcode"] != 0:
            raise OfficialAPIError("{}: {}".format(json_data["errcode"], json_data["errmsg"]))

    def _request(self, method, url, **kwargs):
        """
        向微信服务器发送请求
        :param method: 请求方法
        :param url: 请求地址
        :param kwargs: 附加数据
        :return: 微信服务器响应的 json 数据
        :raise HTTPError: 微信api http 请求失败
        """
        if "params" not in kwargs:
            kwargs["params"] = {
                "access_token": self.access_token,
            }
        if isinstance(kwargs.get("data", ""), dict):
            body = json.dumps(kwargs["data"], ensure_ascii=False)
            body = body.encode('utf8')
            kwargs["data"] = body

        r = requests.request(
            method=method,
            url=url,
            **kwargs
        )
        r.raise_for_status()
        response_json = r.json()
        self._check_official_error(response_json)
        return response_json

    def _get(self, url, **kwargs):
        """
        使用 GET 方法向微信服务器发出请求
        :param url: 请求地址
        :param kwargs: 附加数据
        :return: 微信服务器响应的 json 数据
        :raise HTTPError: 微信api http 请求失败
        """
        return self._request(
            method="get",
            url=url,
            **kwargs
        )

    def _post(self, url, **kwargs):
        """
        使用 POST 方法向微信服务器发出请求
        :param url: 请求地址
        :param kwargs: 附加数据
        :return: 微信服务器响应的 json 数据
        :raise HTTPError: 微信api http 请求失败
        """
        return self._request(
            method="post",
            url=url,
            **kwargs
        )

    def _transcoding(self, data):
        """
        编码转换
        :param data: 需要转换的数据
        :return: 转换好的数据
        """
        if not data:
            return data

        result = None
        if isinstance(data, str):
            result = data.decode('utf-8')
        else:
            result = data
        return result

    def _transcoding_list(self, data):
        """
        编码转换 for list
        :param data: 需要转换的 list 数据
        :return: 转换好的 list
        """
        if not isinstance(data, list):
            raise ValueError('Parameter data must be list object.')

        result = []
        for item in data:
            if isinstance(item, dict):
                result.append(self._transcoding_dict(item))
            elif isinstance(item, list):
                result.append(self._transcoding_list(item))
            else:
                result.append(item)
        return result

    def _transcoding_dict(self, data):
        """
        编码转换 for dict
        :param data: 需要转换的 dict 数据
        :return: 转换好的 dict
        """
        if not isinstance(data, dict):
            raise ValueError('Parameter data must be dict object.')

        result = {}
        for k, v in data.items():
            k = self._transcoding(k)
            if isinstance(v, dict):
                v = self._transcoding_dict(v)
            elif isinstance(v, list):
                v = self._transcoding_list(v)
            else:
                v = self._transcoding(v)
            result.update({k: v})
        return result
