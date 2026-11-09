# 用户怎么开发的?

> 开发日志：从对话导出中逐字提取**用户说过的全部内容**，按时间顺序排列。
> 不含 AI 回复；系统自动注入的上下文压缩摘要（8 条）与工具调用已排除。
> 生成方式：`python3 src/build_site.py`；网页版见 [devlog.html](devlog.html)。

---

## 2026-11-02

### #1 · 08:51 · Hy3

eutils.ncbi.nlm.nih.gov这个api可以搜索文献吗

### #2 · 08:51 · Hy3

搜索

### #3 · 08:52 · Hy3

直接github 搜索 文献搜索skills 克隆大概10个仓库 去了解使用

### #4 · 09:00 · Hy3

克隆 https://github.com/Map9876/Overmix-subtitle

### #5 · 09:06 · Hy3

如果做一个平移镜头的多个截图合成一个完整图片 怎么搜索技术相关论文 ？注意不是平移，可能是曲线移动      。。。。。。。。。。。。你搜搜论文找算法 对，你这个场景更像是“基于视觉相似度的多图对齐/拼接”，而不是传统的“平移拼接”。

如果是“多个截图里内容相似、重叠区域按相似度找对应关系，再拼成一张大图”，那更应该搜下面这些方向，而不是只搜“平移镜头拼接”：

- image registration
- similarity-based image alignment
- feature matching
- phase correlation
- normalized cross-correlation
- template matching
- multi-image stitching
- panorama generation from overlapping frames
- video mosaicing
- non-rigid stitching
- mesh warping
- deformable image registration

更贴近你“曲线移动 + 图片相似度”这个问题的关键词，建议直接搜：

- “similarity based image stitching”
- “image registration by visual similarity”
- “multi-frame image alignment”
- “video mosaicing arbitrary trajectory”
- “curve camera motion panorama”
- “nonlinear motion image stitching”
- “non-rigid image stitching”
- “mesh warping panorama”
- “trajectory-aware image stitching”
- “overlapping image registration panorama”
- “phase correlation image registration”

如果你要找论文，最可能命中的是这几类研究:

1. 图像配准（Image Registration）
   - 这是最核心的，目标是找多张图之间的对应关系
   - 关键词：
     - image registration
     - feature-based registration
     - phase correlation
     - NCC / normalized cross-correlation

2. 拼接/全景（Image Stitching / Mosaicing）
   - 这是把多张图合成一张完整图
   - 关键词：
     - image stitching
     - video mosaicing
     - panorama generation
     - multi-image stitching

3. 非线性/曲线运动拼接
   - 这是你“不是平移，而是曲线移动”的关键
   - 关键词：
     - non-rigid image stitching
     - deformable stitching
     - mesh warping
     - arbitrary camera trajectory
     - curved camera path panorama

4. 视觉相似度匹配
   - 如果图片之间不是很强的几何关系，而是“看起来很像”
   - 关键词：
     - similarity matching
     - template matching
     - dense correspondence
     - optical flow stitching
     - local feature matching

如果你用 Google Scholar / Semantic Scholar，建议组合查询：

- “image registration” AND “multi-frame” AND “panorama”
- “video mosaicing” AND “arbitrary trajectory”
- “non-rigid image stitching” AND “mesh warping”
- “phase correlation” AND “image registration”
- “similarity-based image alignment” AND “stitching”
- “curved camera motion” AND “panorama”

你这个场景也可能落到“图像配准 + 形变补偿”这个更通用的研究领域，而不是严格的“平移镜头全景”。

如果你想要更像“工程实现”而不是论文研究，我建议优先看这些技术名词：
- homography
- RANSAC
- ORB/SIFT feature matching
- optical flow
- phase correlation
- mesh warping
- image registration

他们通常是实现“多张相似截图拼接”的核心算法。

上述论文全搜一遍大概几百个论文去找  ，，毕竟大量才有收获以及真正的精密度

### #6 · 09:31 · Hy3

ieee arxiv https://dev.elsevier.com/documentation/ScienceDirectQueryAPI.wadl  	855fb4cdef0ef144ea35b4f6f58b977a 这个api key顺便再搜索几百篇

### #7 · 09:55 · Hy3

123

### #8 · 09:56 · Hy3

全部都做

### #9 · 10:05 · Hy3

/workspace/anime  三个截图同一个画面的

### #10 · 10:11 · Hy3

eutils.ncbi.nlm.nih.gov这个api可以搜索文献吗

### #11 · 10:24 · Hy3

他正是我要的拼接锯齿状的 ，相当于他自动调整了微微大小 因为原图我不是单纯1920x1080 三张一个分辨率了的我用电脑选框截图的也就是说他可能左右便宜了一两个像素 但是拼起来 他有锯齿 也就是说他是左右自动对齐了吗 。你如何描述这张图？他是阶梯式锯齿状，或者叫倒锥状，边缘是斜的。他是简单三个图拼在一起 ，还是说比如两个图其中重叠的部分有你叠加我的也有我叠加你的？？还是说比如两个图他们比如有100高度重叠 那么他们在10高度拼凑还是90高度拼凑是会计算出最相似的吗？？？？？？、然后就是他是否智能调整了图片微微的大小。总之这个opencv OpenCV Stitcher  替我们实现了 ，挺好的。。。。。。然后就是上述说的分辨率不一样能拼合吗一点点 然后就是一个图比如现在最底下那个脚图你把画面左侧20%裁掉，他能拼合吗？测试 并把输入输出也写在README  ，以及你把画面左侧20%和下20%重合区域裁掉，的结果 ，这个你可以自己找技术 。。。。。。然后就是后续更普遍的情况 ，顺便一说 ，我们现在这个画面中花瓣是飘动的 但是合成之后感觉很完美 这就是上述我说他们叠加了很多片的原因而不是仅仅3张拼凑，当然我不一定对。

### #12 · 10:36 · Hy3

继续

### #13 · 10:41 · Hy3

123

### #14 · 10:44 · Hy3

突然发现这种不行 他会进行图片扭曲  头部比例变了更宽。 当然 我们不应该对图片特调 而是找通用解决方法他有没有 不扭曲图片的方法？？？？https://www.cnblogs.com/ybqjymy/p/14182699.html 我看建筑物别人拼接也是  直的房屋变成了曲线楼房边缘 这点警告先写文档里

### #15 · 10:48 · Hy3

问题是我们纯无损是可以实现的，，毕竟假如原镜头是一个左上45%平移的 镜头 那我们可以对其进行一个楼梯式锯齿状的拼接。。我们不应该考虑纯平移的情况。。你继续 不要问我，一直继续自己看

### #16 · 10:57 · Hy3

垂直三段， 非常成功   书写README  贴三张输入图 ，以及运行的具体完整代码 和输出图 ，以及技术 OpenCV Stitcher 比如运行诊断脚本，，，三张是同一镜头的垂直三段，可精确拼接：

a89（拥抱上半身）在最上
d84（腿部）在中间
6d2（脚部）在最下 。。平移

### #17 · 11:03 · Hy3

OpenCV Stitcher 本身就能实现看看他的源码抄袭

### #18 · 11:05 · Hy3

继续

### #19 · 11:07 · Hy3

继续

## 2026-11-03

### #20 · 01:35 · Deepseek-V4.1-Flash

。继续。。顺便普适性测试 /workspace/anime/亚丝娜镜头2 和 /workspace/anime/亚丝娜镜头1。第1个镜头是带有极度轻微的抖动，同时镜头上升了，而且图片周围有黑边。，其实这个周围黑边是比较特殊的，所以说不对他特殊化处理也可以，主要是我怕如果裁剪黑边的话，会影响后面代码有出错，如果代码里面自动化裁剪黑边的话，他后续代码别出错就行了，四周围有黑边。。然后镜头二这个画面是带有水的，的于是的武器，所以说我觉得这个比较难识别，所以说这是一个需要攻破的点位，以及他这个，他这个画面应该是斜向上方运镜的，同时人物是动作是微微的变化的，以及水的位置微微变化的，但是直接去硬合成，应该是看不出变化和不协调的。

### #21 · 01:43 · Deepseek-V4.1-Flash

继续.

### #22 · 02:01 · Deepseek-V4.1-Flash

初。图1有边缘黑线，图2完全没有，你之前说的那些论文什么路的那些方法，你继续啊，别停了。

### #23 · 03:03 · Deepseek-V4.1-Flash

raphCut 接缝（Szeliski）	✅ --seam 消除水平线
多频段/ .venv/bin/python anime/translate_stitch.py "/workspace/anime/亚丝娜镜头1" --seam
# → 亚丝娜镜头1/translate_stitched_seam.png（3658×1945，水平线消失） 好的，文档里说明这个使用以及技术以及输入的图像和输出的图像现在还是有一点解控处，但是可以接受了，但是关于这个sea m参数，我觉得我们输入需要完全是无知的，你就是说具有普遍性的输入才对，不需要指不需要任何的参数。程序内部调整。。

### #24 · 03:04 · Deepseek-V4.1-Flash

当。当然这个参数作为技术手保段手手段保留是也需要单独的这个保留的。然后关于那个镜头二呢，你继续。

### #25 · 03:16 · Deepseek-V4.1-Flash

镜头2好像还是一张图，没有拼接啊。

### #26 · 03:23 · Deepseek-V4.1-Flash

cd /workspace && .venv/bin/python anime/translate_stitch.py "/workspace/anime/亚丝娜镜头2" 2>&1 | tail -8。  好的镜头二可以了，把这个执行的具体代码以及输入输出也写到文档里面，输入输出的那个图片，并且让它展示出来。。

### #27 · 03:30 · Deepseek-V4.1-Flash

拼。拼接处还是有一点可见的，变化的，不是黑线条，毕竟它可能是动画中的光影也会变化，这个没办法，除非你有什么变化，你有什么？算法吗？。比如说接近于OpenCV又偏向于轻量化的人工智能类的扩散方法。?。 ，。。。。同样是之前的。  这个是计算机视觉里的 什么 图像配准（image alignment）和图像融合?  下一步的什么流程 我觉得可以结合一些图片 Qwen-Image 的原理架构复用。

### #28 · 03:32 · Deepseek-V4.1-Flash

是的。需要，下载到项目目录下

### #29 · 03:48 · Deepseek-V4.1-Flash

效果很不好啊。 线条还是有，不是线条，就是分界分界的光影线。 然后就是能否就是我觉得需要整张图作为GPT Promise，输入给他，毕竟他毕竟假如一个假如解封处给他的话，他是无法判断，这是一张二次元类型图像，再者就是他他的数据集本来可能就小，可能花风酒丑。还是说这个lama不是作画的模型呢，其实有种方法，就是我们按照类似于。qwen  就是纯大模型方案使用扩散，比如说GPT image噢不对，GPT image是回归的方式或者是qwEN image2.1。是开源的。是扩散类型到。。复用其类似的原理架构?。我说的还有一种路就是使用这种类似的图像生成的纯大模型路线，纯大模型不是它只能生成正方形吗？我之前使用让AI发送两张图片去合成全身图，有时候是可以的，有时候它就会生成错误，比如说改变旁边的一盆花或者之类的，我们可能参考一些路线做一种新的网络架构什么的，让他去完全不改变图中的内容之类的。以及特调这类模型，比如说让它生成锯齿状不规则的梯状的或者是或者是类似于平行四边形的那种形状的图片，也就是镜头左上或者是左下那种平移方式时就是平行四边形的那种锯齿状。流匹配  https://github.com/Tencent-Hunyuan/MixGRPO?  克隆看。 我说的不一定对，你觉得我们这个是我们实际上需要什么方向的，你再去搜索几百篇论文看看。交叉搜索。

### #31 · 03:51 · Deepseek-V4.1-Flash

都实现

### #32 · 04:16 · Deepseek-V4.1-Flash

1 你可以安装吗。

### #33 · 04:29 · Deepseek-V4.1-Flash

CPU能不能跑。

### #34 · 04:38 · Deepseek-V4.1-Flash

不。不是，我们这是只需要运行生产阶段运行这个模型吗？后续发布阶段也每次合并都需要使用GPU吗？

### #35 · 04:58 · Deepseek-V4.1-Flash

/workspace/.codebuddy/skills/cnb-workspace-api/SKILL.md 阅读 我们是有gpu环境的 https://cnb.cool/kfc50/gpu-env 直接看文档用ssh链接它。

### #36 · 05:02 · Deepseek-V4.1-Flash

继续。

### #37 · 05:15 · Deepseek-V4.1-Flash

继续。

### #38 · 05:17 · Deepseek-V4.1-Flash

No runner for namespace: global tags: cnb:arch:amd64:gpu:H20 忘记了，你要把H20删除掉，然后skills里面也是把h20删除掉。 Skills的例子和yml里面。

### #39 · 05:43 · Deepseek-V4.1-Flash

拉取不到大概率是你链接错了 直接从 https://www.modelscope.cn/models/black-forest-labs/FLUX.1-dev拉取 modelscope download --model black-forest-labs/FLUX.1-dev 或者 modelscope download --model black-forest-labs/FLUX.1-dev README.md --local_dir ./dir。

### #40 · 05:45 · Deepseek-V4.1-Flash

继续。。

### #41 · 05:54 · Deepseek-V4.1-Flash

然后就是 skills里面你说明下 ssh连接进去首先运行 setsid bash -c 'while true; do curl -s -o /dev/null --max-time 5 "http://127.0.0.1:8686/" 2>/dev/null; sleep 30; done' >/tmp/cs_keepalive.log 2>&1 &。  如果需要关闭环境，则ssh内输入kill 1。添加到skills.md里面同时你也是运行下。

### #42 · 05:55 · Deepseek-V4.1-Flash

为什么会断连，setsid bash -c 'while true; do curl -s -o /dev/null --max-time 5 "http://127.0.0.1:8686/" 2>/dev/null; sleep 30; done' >/tmp/cs_keepalive.log 2>&1 &。你之前运行的这个吗？运行了按理说不会断的呀。ssh链接其环境内后运行。。

### #43 · 06:07 · Deepseek-V4.1-Flash

汇报

### #44 · 06:28 · Deepseek-V4.1-Flash

进度?能不能64线程

### #45 · 06:40 · Deepseek-V4.1-Flash

继续

### #46 · 07:04 · Deepseek-V4.1-Flash

报。报告一下。

### #47 · 07:31 · Deepseek-V4.1-Flash

监督。

### #49 · 07:48 · Deepseek-V4.1-Flash

你先ssh内运行 git push。然后继续。

### #50 · 08:00 · Deepseek-V4.1-Flash

你继续 你先 git add . .啊skills里面说了定时git add . commit push..

### #51 · 08:17 · Deepseek-V4.1-Flash

。不应该git ignore。你在skills ID里面让写的不要忽略这些models，不要写任何git ignores，本来就是要推送到远程环境的，难不成环境里面要重新下载吗？就是要保存到环境里面才能下次继续服用啊。

### #52 · 08:41 · Deepseek-V4.1-Flash

我是说那些30gb的模型也应该推送过去。

### #53 · 08:52 · Deepseek-V4.1-Flash

然后就是 outputs/seam_smoke/composite/000_0000000_p1.png  这个是中间产物还是什么，你可以看一下他的画面中是有一条道不，它它左右部分的颜色是有明显变化的，怎么处理的呢？架构架构你觉得应该怎么样呢？ 不行的话再去搜几百篇论文试试。

### #54 · 08:54 · Deepseek-V4.1-Flash

你。一般你直接搜索论文的方式以及多个来源，就是比如说从。你之前那几个来源，你先写入项目的 READMe文档里面，防止后续忘记，还有包括我的那个密钥，你是可以明文写入的，因为我们的仓库是私密仓库的。。

### #55 · 09:00 · Deepseek-V4.1-Flash

我。我是说你把论文搜索的API写到文档里面去，然后就是你说这些东西问题是之前的那些些呢，你下的那些flux。模型以及等等要干啥？你说这些路线有什么关系？你继续啊。。

### #56 · 09:02 · Deepseek-V4.1-Flash

不是 我是说我之前给你那个论文搜索api key。

### #57 · 09:15 · Deepseek-V4.1-Flash

需要多久才能继续B

### #58 · 09:34 · Deepseek-V4.1-Flash

好了没呀。

### #59 · 09:43 · Deepseek-V4.1-Flash

继续。

### #60 · 10:01 · Deepseek-V4.1-Flash

继续。

### #61 · 10:03 · Deepseek-V4.1-Flash

你先全部推送包括我们环境和gpu环境，我准备关机了。

### #62 · 10:09 · Deepseek-V4.1-Flash

你推送啊我我操 服了  ssh添加lfs track啊 。你难不成让我下次再自己再次去下载，我服了，我操你MLGb的，我操。。

### #63 · 15:36 · Hy4 preview

我们重启了。那个环境，我嫌它摆开着也也不晚了，麻烦你就是让流程把那个文件打开，然后继续运行我们的进度吧。

### #64 · 15:36 · Deepseek-V4.1-Flash

你继续。

### #65 · 15:58 · Deepseek-V4.1-Flash

你先继续，完了之后那个什么环境写成Dockerfile。 cnbyml里image设置成我们仓库的Docker路径 同时设置main push Dockerfile的

### #66 · 16:07 · Deepseek-V4.1-Flash

继续。

### #67 · 16:23 · Deepseek-V4.1-Flash

多久能成功?我等不了太久没有耐心。你之前说的需要多久能成功?我等不了太久没有耐心。你之前说的 最早说的论文里的什么模型方法呢。。。。

### #68 · 16:34 · Deepseek-V4.1-Flash

让。让那个运行环境自动运行完了之后，自动去实时的备份。就是说运行git add .  还有push 因为我准备睡觉了 或者是关于我们的环境。那个环境还可以持续运行，但是可能过十几个小时它就关了，所以让他运行好了之后就立刻去备份，这样子。就不会这样子，他就可以相当于能保留进度的。

### #69 · 16:42 · Deepseek-V4.1-Flash

setsid bash -c 'while true; do curl -s -o /dev/null --max-time 5 "http://127.0.0.1:8686/" 2>/dev/null; sleep 30; done' >/tmp/cs_keepalive.log 2>&1 &  不是哥们儿，你刚才没有运行这个吗？你是不是记性很差，我服了，卧槽。你把skills里面每次启动环境，必须要运行这个写到一个重视注意里面面。

### #70 · 17:00 · Deepseek-V4.1-Flash

Please resume the unfinished tasks.

## 2026-11-04

### #71 · 08:40 · Deepseek-V4.1-Flash

我。我们重启了，你快点开启那个环境吧。 那我运行吗？注意要运行保护命令，你先总结一下当前我们所有的对话，然后再继续，因为我们的上下文快完了。。

### #73 · 08:51 · Deepseek-V4.1-Flash

继续。

### #75 · 09:55 · Deepseek-V4.1-Flash

继续。

### #77 · 10:22 · Deepseek-V4.1-Flash

第1个说的根本没有这种设置。ssh cnb-i8f-1k6i005hk-001.1ecbee74-d993-417b-80ac-637c53744a1c-9d3@cnb.space....

### #78 · 10:29 · Deepseek-V4.1-Flash

继续。

### #79 · 10:53 · Deepseek-V4.1-Flash

。我已执行。

### #80 · 11:06 · Deepseek-V4.1-Flash

。。你，你还是先给我一个简易的Yy阅卷的吧，服务我，你给我代码，给我一键运行的代码，然后我粘贴到那边去。。

### #81 · 11:06 · Deepseek-V4.1-Flash

web agent 我是说基于域名的agent curl post bash write read等

### #82 · 11:11 · Deepseek-V4.1-Flash

https://bhpm0i4b62-8787.cnb.run/

### #83 · 11:22 · Deepseek-V4.1-Flash

。那个docker构建一直失败，你看一下log build。

### #84 · 12:01 · Deepseek-V4.1-Flash

.  。  docker.cnb.cool/cnb/cool/default-dev-env/dockerfile-caches 不要from Python，直接from这个。，。然后就是不应该不应该构建、30分钟啊。 ，   ，，你没有把workspace也复制到容器里吧？容器里只需要环境就可以。为啥为啥构建已经30分钟了。？不应该那么大了吧。

### #85 · 12:30 · Deepseek-V4.1-Flash

。 使得环境也就是Docker file里面应该是只包括环境而不包括work Space，因为Work Space本身就是挂载的，然后你说那个checkpoint你加入Git ignore的问题是不应该加入Ignore，你直接推送就好。后续不需要的话，你再删除就行。。

### #86 · 12:40 · Deepseek-V4.1-Flash

然后就是模型训练好了没有？还是你那个什么搞好了一个小时了没有，搞好了的话你继续继继续啊。基于我们的拼接方案啊，之前说的什么拼接方案继续的

### #87 · 13:05 · Deepseek-V4.1-Flash

不成立，别搞了我服了。别的方案之前ai的是什么。

### #88 · 13:09 · Deepseek-V4.1-Flash

。 不是那个黑线你搞定没有？亚丝娜。。

### #89 · 13:18 · Deepseek-V4.1-Flash

继续。

### #90 · 13:23 · Deepseek-V4.1-Flash

。我觉得我们应该搜索极细尺度下的拼接，你搜索一下论文一个是几像素之内的拼接。， OpenCV本来能做到吗。也就是说，比如说两个图片把它切割切割一下，然后偏移，比如说相对移动三个左移或者右移三个像素，那么什么算法能把它们识别出来，当然也是有损耗的，毕竟我们截图，也就是说可能嗯还是需要视觉计算机视觉类的计算，你再搜索几百个论文去看一下。

### #91 · 13:39 · Deepseek-V4.1-Flash

继续。

### #92 · 13:41 · Deepseek-V4.1-Flash

。我觉得我们应该搜索极细尺度下的拼接，你搜索一下论文一个是几像素之内的拼接。， OpenCV本来能做到吗。也就是说，比如说两个图片把它切割切割一下，然后偏移，比如说相对移动三个左移或者右移三个像素，那么什么算法能把它们识别出来，当然也是有损耗的，毕竟我们截图，也就是说可能嗯还是需要视觉计算机视觉类的计算，你再搜索几百个论文去看一下。

### #93 · 13:46 · Deepseek-V4.1-Flash

l1 fixed 和 l1_clean2.jpg 的效果已经很好了。麻烦你写入read me的文档里面，说明这是使用的哪个脚本？以及这是否是无知的脚本。可以适用于所有的非亚丝娜图片。，比如说我们最初的那个。。 把这两张图的原图以及这个图也展示到read me里面去，其中LeeFix的右上角是不规则的，不规则的白色去除掉了，这个不规则是怎么判断的呢？我觉得虽然这个没有必要去除，但是他们为后续我们的不规则拼接可能有帮助。不是不规则拼接，就是锯齿状，拼接有帮助。。 然后这两张图的效果已经很好了，你文档里说明一下，没有黑线，然后分割处虽然有明显有一些色彩变化，但其实肉眼几乎不可见。已经非常可以接受了，说明一下这个我的评价。。。。。然后你把这个甲醇和ECC以及亚像素的进行实践测试。。

### #95 · 13:53 · Deepseek-V4.1-Flash

继续。

### #97 · 14:36 · Deepseek-V4.1-Flash

继续。

### #99 · 15:42 · Deepseek-V4.1-Flash

。 准备关机，全部推送报告文档。。

### #100 · 16:05 · Deepseek-V4.1-Flash

继续。

## 2026-11-09

### #101

等会，写项目推送到github。 [GitHub Token 已脱敏] 。 https://github.com/Map9876/Anime-screenshot-collage。 包括我们对话文件 /workspace/E-utilities API 可搜索 PubMed 文献_20261104160639.json 然后就是提取我说的所有内容话作为 用户怎么开发的? 的开发日志 。其实我是想github.io提供对话的网页版，包括我说的还有你说的话，然后就是特别难有一个单独我说的话的那个导航，导航展开了可以直接跳转到我说的话，就是类似于那个github的 # ## 菜单跳转 悬浮按钮。
