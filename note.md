# 全局要求
使用本项目路径下的./venv执行python命令、安装python依赖  
涉及网络交互的代理http://127.0.0.1:10801，支持配置其他地址和是否开启

# 项目背景
danbooru是二次元插画网站，使用danbooru风格的英文单词对图片进行打标，danbooru官方对各种tag进行了分类，多个tag属于一个tag group。  
我抓取了各个tag group的json放到data/tag_group下。  
现在需要对已经整理完成的danbooru tag进行精准的中文翻译。  
翻译借助llm。
danbooru tag使用非常简略的英文，单独送给llm可能无法准确得到结果。  
danbooru官方还提供了对tag的wiki说明，这次翻译任务需要用来补全tag的上下文。  
wiki数据在data/danbooru_wikis_full/wiki_pages.parquet下，读取方式参考search_wiki.py


# 项目

# 你需要给出的
1. python脚本 从 tag JSON + wiki parquet 自动构造上下文  
{
  "tag": "cock_ring",
  "group_name": "sex_objects",
  "category_path": "Sex Toys",
  "wiki": "A ring at the base of the penis that constricts blood flow to help 
}  
整理出所有需要翻译的tag清单
2. 要求llm翻译输出的JSON格式  
confidence取值A = 很确定
B = 基本确定
C = 有歧义
D = 需要人工审核
{
  "tag": "cock_ring",
  "tag_cn": "阴茎环",
  "confidence": "A",
  "tag_cn_long": "套在阴茎根部用于维持勃起的性玩具。"
}  
一个tag group的所有结果最后合并成一个文件
3. 工程需求  
断点续跑
结果缓存
失败重试  
并发调用llm接口
4. 考虑方案  
方案 A：质量优先
每条单独调用
成本高，但最准
方案 B：均衡推荐
10~20 条一批
输出 JSON 数组


# 调用的llm的接口文档：
首次调用 API
DeepSeek API 使用与 OpenAI/Anthropic 兼容的 API 格式，通过修改配置，您可以使用 OpenAI/Anthropic SDK 来访问 DeepSeek API，或使用与 OpenAI/Anthropic API 兼容的软件。

PARAM	VALUE
base_url (OpenAI)	https://api.deepseek.com
base_url (Anthropic)	https://api.deepseek.com/anthropic
api_key	apply for an API key
model*	deepseek-v4-flash
deepseek-v4-pro


调用对话 API
在创建 API key 之后，你可以使用以下样例脚本，通过 OpenAI API 格式来访问 DeepSeek 模型。样例为非流式输出，您可以将 stream 设置为 true 来使用流式输出。

Anthropic API 格式的访问样例，请参考Anthropic API。

Please install OpenAI SDK first: `pip3 install openai`
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com")

response = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=[
        {"role": "system", "content": "You are a helpful assistant"},
        {"role": "user", "content": "Hello"},
    ],
    stream=False,
    reasoning_effort="high",
    extra_body={"thinking": {"type": "enabled"}}
)

print(response.choices[0].message.content)

# llm代码必要参数
支持使用模型  
deepseek-v4-flash  
deepseek-v4-pro  
api key配置为sk-f035d1e0c2354c4eaf809c9f3526fd99

