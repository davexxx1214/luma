import json
import re
import plugins
from bridge.reply import Reply, ReplyType
from bridge.context import ContextType
from channel.chat_message import ChatMessage
from plugins import *
from common.log import logger
from common.tmp_dir import TmpDir
from common.expired_dict import ExpiredDict


import os
from kling import VideoGen
import os
import uuid
from glob import glob
import translators as ts


@plugins.register(
    name="lumaplayer",
    desire_priority=2,
    desc="A plugin to call klingAI API",
    version="0.0.2",
    author="davexxx",
)

class lumaplayer(Plugin):
    def __init__(self):
        super().__init__()
        try:
            curdir = os.path.dirname(__file__)
            config_path = os.path.join(curdir, "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
            else:
                # 使用父类的方法来加载配置
                self.config = super().load_config()

                if not self.config:
                    raise Exception("config.json not found")
            
            # 设置事件处理函数
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            # 从配置中提取所需的设置
            self.cookie = self.config.get("cookie","")
            self.kling_img_prefix = self.config.get("kling_img_prefix", "kling")
            self.kling_text_prefix = self.config.get("kling_text_prefix", "kling_text")
            self.params_cache = ExpiredDict(500)

            # 初始化成功日志
            logger.info("[klingplayer] inited.")
        except Exception as e:
            # 初始化失败日志
            logger.warn(f"klingplayer init failed: {e}")

    def on_handle_context(self, e_context: EventContext):
        context = e_context["context"]
        if context.type not in [ContextType.TEXT, ContextType.SHARING,ContextType.FILE,ContextType.IMAGE]:
            return
        msg: ChatMessage = e_context["context"]["msg"]
        user_id = msg.from_user_id
        content = context.content

        # 将用户信息存储在params_cache中
        if user_id not in self.params_cache:
            self.params_cache[user_id] = {}
            self.params_cache[user_id]['kling_img_quota'] = 0
            self.params_cache[user_id]['img_prompt'] = None
            self.params_cache[user_id]['text_prompt'] = None

            logger.debug('Added new user to params_cache. user id = ' + user_id)

        if e_context['context'].type == ContextType.TEXT:
            if content.startswith(self.kling_img_prefix):
                pattern = self.kling_img_prefix + r"\s(.+)"
                match = re.match(pattern, content)
                if match: ##   匹配上了kling的指令
                    img_prompt = content[len(self.kling_img_prefix):].strip()
                    self.params_cache[user_id]['img_prompt'] = img_prompt
                    self.params_cache[user_id]['kling_img_quota'] = 1
                    tip = f"💡已经开启kling图片生成视频服务，请再发送一张图片进行处理，当前的提示词为:\n{img_prompt}"
                else:
                    tip = f"💡欢迎使用kling图片生成视频服务，指令格式为:\n\n{self.kling_img_prefix} + 对视频的描述\n例如：{self.kling_img_prefix} make the picture alive."

                reply = Reply(type=ReplyType.TEXT, content= tip)
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS

            elif content.startswith(self.kling_text_prefix):
                pattern = self.kling_text_prefix + r"\s(.+)"
                match = re.match(pattern, content)

                if match: ##   匹配上了kling的指令
                    text_prompt = content[len(self.kling_text_prefix):].strip()
                    self.params_cache[user_id]['text_prompt'] = text_prompt
                    self.call_kling_service(None, user_id, e_context)
                else:
                    tip = f"💡欢迎使用kling文字生成视频服务，指令格式为:\n\n{self.kling_text_prefix} + 对视频的描述\n例如：{self.kling_text_prefix} a girl is walking in the street."
                    reply = Reply(type=ReplyType.TEXT, content= tip)
                    e_context["reply"] = reply
                    e_context.action = EventAction.BREAK_PASS
                

        elif context.type == ContextType.IMAGE:
            if self.params_cache[user_id]['kling_img_quota'] < 1:
                # 进行下一步的操作                
                logger.debug("on_handle_context: 当前用户生成视频配额不够，不进行识别")
                return

            logger.info("on_handle_context: 开始处理图片")
            context.get("msg").prepare()
            image_path = context.content
            logger.info(f"on_handle_context: 获取到图片路径 {image_path}")

            if self.params_cache[user_id]['kling_img_quota'] > 0:
                self.params_cache[user_id]['kling_img_quota'] = 0
                self.call_kling_service(image_path, user_id, e_context)

            # 删除文件
            os.remove(image_path)
            logger.info(f"文件 {image_path} 已删除")
    
    def translate_to_english(self, text):
        logger.info(f"translate text = {text}")
        return ts.translate_text(text, translator='google')
    
    def generate_unique_output_directory(self, base_dir):
        """Generate a unique output directory using a UUID."""
        unique_dir = os.path.join(base_dir, str(uuid.uuid4()))
        os.makedirs(unique_dir, exist_ok=True)
        return unique_dir
    
    def is_valid_file(self, file_path, min_size=100*1024):  # 100KB
        """Check if the file exists and is greater than a given minimum size in bytes."""
        return os.path.exists(file_path) and os.path.getsize(file_path) > min_size

    def call_kling_service(self, image_path, user_id, e_context):
        logger.info("call_kling_service")

        if image_path:
            prompt = self.params_cache[user_id]['img_prompt']
        else:
            prompt = self.params_cache[user_id]['text_prompt']

        output_dir = self.generate_unique_output_directory(TmpDir().path())
        logger.info(f"output dir = {output_dir}")

        tip = '欢迎光临神奇的视频制造厂！🎥✨ 放松，倒一杯咖啡☕️，伸个懒腰🧘‍♂️。让我们的小精灵们为你打造专属视频。稍坐片刻，2-5分钟后，您的视频即将呈现！🎬✨'
        self.send_reply(tip, e_context)

        try:
            v = VideoGen(self.cookie)  # Replace 'cookie', image_url with your own
            if not image_path:
                v.save_video(prompt, output_dir)
            else:
                v.save_video(prompt, output_dir, image_path)
        except Exception as e:
            logger.error("call kling api error: {}".format(e))
            rt = ReplyType.TEXT
            rc = f"服务暂不可用: {e}"
            reply = Reply(rt, rc)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            return

        
        # 查找 output_dir 中的 mp3 和 mp4 文件
        mp4_files = glob(os.path.join(output_dir, '*.mp4'))
        for file_path in mp4_files:
            if self.is_valid_file(file_path):
                logger.info(f"File {file_path} is valid.")
                newfilepath = self.rename_file(file_path, prompt)
                rt = ReplyType.VIDEO
                rc = newfilepath
                self.send_reply(rc, e_context, rt)
            else:
                logger.info(f"File {file_path} is invalid or incomplete.")
                rt = ReplyType.TEXT
                rc = "视频生成失败，请稍后再试"
                e_context["reply"] = reply
                break  # 如果某个文件无效，则跳出循环

        e_context.action = EventAction.BREAK_PASS
        
    def send_reply(self, reply, e_context: EventContext, reply_type=ReplyType.TEXT):
        if isinstance(reply, Reply):
            if not reply.type and reply_type:
                reply.type = reply_type
        else:
            reply = Reply(reply_type, reply)
        channel = e_context['channel']
        context = e_context['context']
        # reply的包装步骤
        rd = channel._decorate_reply(context, reply)
        # reply的发送步骤
        return channel._send_reply(context, rd)
    
    def rename_file(self, filepath, prompt):
        # 提取目录路径和扩展名
        dir_path, filename = os.path.split(filepath)
        file_ext = os.path.splitext(filename)[1]

        # 移除prompt中的标点符号和空格
        cleaned_content = re.sub(r'[^\w]', '', prompt)
        # 截取prompt的前10个字符
        content_prefix = cleaned_content[:10]
                
        # 组装新的文件名
        new_filename = f"{content_prefix}"

        # 拼接回完整的新文件路径
        new_filepath = os.path.join(dir_path, new_filename + file_ext)

        # 重命名原文件
        try:
            os.rename(filepath, new_filepath)
        except OSError as e:
            logger.error(f"Error: {e.strerror}")
            return filepath

        return new_filepath