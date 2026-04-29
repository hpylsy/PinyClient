

# PinyClient

RoboMaster Pioneer战队自定义客户端，支持基础MQTT服务，英雄低带宽图传

<!-- PROJECT SHIELDS -->

[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]
[![LinkedIn][linkedin-shield]][linkedin-url]

<!-- PROJECT LOGO
<br />

<p align="center">
  <a href="https://github.com/SCNU-PIONEER/PinyClient/">
    <img src="images/logo.png" alt="Logo" width="80" height="80">
  </a>

  <h3 align="center">"完美的"README模板</h3>
  <p align="center">
    一个"完美的"README模板去快速开始你的项目！
    <br />
    <a href="https://github.com/SCNU-PIONEER/PinyClient"><strong>探索本项目的文档 »</strong></a>
    <br />
    <br />
    <a href="https://github.com/SCNU-PIONEER/PinyClient">查看Demo</a>
    ·
    <a href="https://github.com/SCNU-PIONEER/PinyClient/issues">报告Bug</a>
    ·
    <a href="https://github.com/SCNU-PIONEER/PinyClient/issues">提出新特性</a>
  </p>

</p> -->


 本篇README.md面向开发者
 
## 目录

- [上手指南](#上手指南)
  - [开发前的配置要求+安装步骤](#开发前的配置要求)
- [文件目录说明](#文件目录说明)
- [作者](#作者)

### 上手指南

``` python 
python3 app.py
```

###### 开发前的配置要求
- Ubuntu22.04（wsl）
- python3（禁用conda与venv，使用全局环境）
- 使用pip安装依赖
``` python
pip install requirements.txt
```
- 安装gi

### 测试说明
- 在`app.py`中，修改CoreService的配置项`consts.TestConfig(if_test=True, if_mqtt_source=True)`，具体配置项在`consts.TestConfig`中
<!-- - 若不希望flask阻碍主线程，可设置`start_flask(blocking=False)` -->
<!-- - 若不希望日志输出到命令行或希望修改日志level，请在`config.Config`中修改 -->
- 目前可用`start_log_or_console(service, start_log=False)`，启用命令行功能（若为start_log=True，则启动普通日志功能）

### 文件目录说明

```
filetree 
├── app.py
├── assets  - 测试视频
│   └── oceans.mp4
├── config.py  - 配置项
├── LICENSE.txt  - 许可证
├── models  - 模型文件夹
│   ├── base.py  - 消息基类
│   ├── consts.py  - 常用常量
│   ├── message.py  - 核心：所有message的包装类
│   ├── protocol  - 协议相关文件夹
│   │   ├── messages_pb2.py  - 基于原始信息文件编译后的python文件
│   │   └── messages.proto  - 原始信息文件
│   └── README.md
├── README.md
├── requirements.txt
├── service  - 服务文件夹
│   ├── core_service.py  - 核心服务
│   ├── img_receiver.py  - 图像接收服务，支持两种图源
│   ├── mqtt_client.py  - mqtt支持服务
│   ├── README.md
│   └── states_manager.py  - 状态机
├── static  - web相关
│   └── css
│       └── style.css
├── templates  - web相关
│   └── index.html
└── tools  - 实用工具
    ├── logs_content  - 日志文件夹
    ├── README.md
    ├── rm_command.py  - 命令行系统（目前未启用）
    └── rm_logger.py  - 彩色日志

```


<!-- ### 开发的架构 

请阅读[ARCHITECTURE.md](https://github.com/SCNU-PIONEER/PinyClient/blob/master/ARCHITECTURE.md) 查阅为该项目的架构。 -->

<!-- ### 部署

暂无

### 使用到的框架

- [xxxxxxx](https://getbootstrap.com)
- [xxxxxxx](https://jquery.com)
- [xxxxxxx](https://laravel.com)

### 贡献者

请阅读**CONTRIBUTING.md** 查阅为该项目做出贡献的开发者。

#### 如何参与开源项目

贡献使开源社区成为一个学习、激励和创造的绝佳场所。你所作的任何贡献都是**非常感谢**的。


1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request



### 版本控制

该项目使用Git进行版本管理。您可以在repository参看当前可用版本。 -->

### 作者

1643001598@qq.com

qq:1643001598

 <!-- *您也可以在贡献者名单中参看所有参与该项目的开发者。* -->

### 版权说明

该项目签署了MIT 授权许可，详情请参阅 [LICENSE.txt](https://github.com/SCNU-PIONEER/PinyClient/blob/master/LICENSE.txt)

<!-- ### 鸣谢


- [GitHub Emoji Cheat Sheet](https://www.webpagefx.com/tools/emoji-cheat-sheet)
- [Img Shields](https://shields.io)
- [Choose an Open Source License](https://choosealicense.com)
- [GitHub Pages](https://pages.github.com)
- [Animate.css](https://daneden.github.io/animate.css)
- [xxxxxxxxxxxxxx](https://connoratherton.com/loaders) -->

<!-- links -->
[your-project-path]:SCNU-PIONEER/PinyClient
[contributors-shield]: https://img.shields.io/github/contributors/SCNU-PIONEER/PinyClient.svg?style=flat-square
[contributors-url]: https://github.com/SCNU-PIONEER/PinyClient/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/SCNU-PIONEER/PinyClient.svg?style=flat-square
[forks-url]: https://github.com/SCNU-PIONEER/PinyClient/network/members
[stars-shield]: https://img.shields.io/github/stars/SCNU-PIONEER/PinyClient.svg?style=flat-square
[stars-url]: https://github.com/SCNU-PIONEER/PinyClient/stargazers
[issues-shield]: https://img.shields.io/github/issues/SCNU-PIONEER/PinyClient.svg?style=flat-square
[issues-url]: https://img.shields.io/github/issues/SCNU-PIONEER/PinyClient.svg
[license-shield]: https://img.shields.io/github/license/SCNU-PIONEER/PinyClient.svg?style=flat-square
[license-url]: https://github.com/SCNU-PIONEER/PinyClient/blob/master/LICENSE.txt
[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=flat-square&logo=linkedin&colorB=555
[linkedin-url]: https://linkedin.com/in/shaojintian




