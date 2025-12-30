-- Featured podcasts insert statements
-- Generated from Listen Notes API

INSERT INTO featured_podcasts (
    podcast_id, 
    priority, 
    title, 
    publisher, 
    image_url, 
    description
) VALUES (
    '887fc174645b4bfd98b181fed10c8e46',
    100,
    'Insider Secrets to a Top 100 Podcast with Courtney Elmer | Podcasting Strategy for Business Growth',
    'Courtney Elmer | PodLaunchHQ.com',
    'https://cdn-images-3.listennotes.com/podcasts/insider-secrets-to-a-top-100-podcast-with-wvLe9VJDbGA-Jp_RfscgbCY.1400x1400.jpg',
    '<p>This isn’t another “share great content and stay consistent” podcast about podcasting. We’re breaking down 15,000+ hours of study into what top hosts do differently to create bingeworthy podcasts that convert.&nbsp;<br>&nbsp;<br>&nbsp;<br>&nbsp;</p><p><br>&nbsp;<br>&nbsp;</p><p>Hosted by Forbes- and Rolling Stone-featured podcast psychology expert and Webby Awards judge Courtney Elmer—who’s helped over 70+ hosts launch Top 100 shows—you’ll get the tools and strategies other shows won’t dare to share. Expect unfiltered coaching, behind-the-scenes breakdowns, and the kind of “why didn’t anyone tell me this sooner?!” advice to help you build a podcast your future clients can’t stop bingeing (and buying from).&nbsp;<br>&nbsp;<br>&nbsp;<br>&nbsp;</p><p><br>&nbsp;<br>&nbsp;</p><p>So if you’re ready to break out of “less-than-200-download-per-episode” jail and stop settling for downloads that don’t reflect your effort—or you want to launch a podcast that positions you as an authority in your niche and drives real revenue—welcome to the podcast that’s about to change the game for you. Hit play and let’s dive in.&nbsp;<br>&nbsp;<br>&nbsp;<br>&nbsp;</p><p><br>&nbsp;<br>&nbsp;</p><p>&nbsp;</p><p>Popular Guests Include: Jordan Harbinger, John Lee Dumas, James Cridland, Tom Rossi, Jeremy Enns, Kevin Chemidlin, Dave Jackson, Alex Sanfilippo, Seth Silvers, Stacy Tuschl, Kate Erickson, Grant Baldwin, Hal Elrod, Gay Hendricks, Brandon Lucero, James Wedmore, and more.&nbsp;<br>&nbsp;<br>&nbsp;<br>&nbsp;</p><p><br>&nbsp;<br>&nbsp;</p><p>&nbsp;</p><p>Popular Episode Topics Include: Podcasting for Business Growth, Starting a Podcast, Podcast Audience Growth, Podcasting for Profit, Podcasting Psychology, Increasing Listener Engagement, Creating Bingeworthy Podcast Content, Lead Generation Through Podcasting,&nbsp; Business Podcasting, Ranking Your Podcast in The Top 100, Podcast Launch Strategy, Podcast Monetization Strategies, Podcast Messaging, Podcast Positioning</p>'
) ON CONFLICT (podcast_id) DO UPDATE SET
    priority = EXCLUDED.priority,
    title = EXCLUDED.title,
    publisher = EXCLUDED.publisher,
    image_url = EXCLUDED.image_url,
    description = EXCLUDED.description,
    updated_at = NOW();
INSERT INTO featured_podcasts (
    podcast_id, 
    priority, 
    title, 
    publisher, 
    image_url, 
    description
) VALUES (
    'abdcce3f264e48f496bac5730fb83e93',
    99,
    'School of Podcasting: Expert Tips for Launching and Growing Your Podcast',
    'Dave Jackson',
    'https://cdn-images-3.listennotes.com/podcasts/school-of-podcasting-plan-launch-grow-and-xOMJWt36E8_-8j0lz94SdR2.1400x1400.jpg',
    'You want to start a podcast, but you’re unsure where to start. You need advice on how to grow or monetize your show, and stop being so scared that it won’t work! I can help by showing you what mistakes NOT TO MAKE and much more. Subscribe to the show and soak in the 18+ years of podcasting experience from Podcaster Hall of Fame Inductee Dave Jackson.'
) ON CONFLICT (podcast_id) DO UPDATE SET
    priority = EXCLUDED.priority,
    title = EXCLUDED.title,
    publisher = EXCLUDED.publisher,
    image_url = EXCLUDED.image_url,
    description = EXCLUDED.description,
    updated_at = NOW();
INSERT INTO featured_podcasts (
    podcast_id, 
    priority, 
    title, 
    publisher, 
    image_url, 
    description
) VALUES (
    '1c6092ae38124ee98d116676afb1e346',
    98,
    'Podcasting Made Simple',
    'Alex Sanfilippo, PodMatch.com',
    'https://cdn-images-3.listennotes.com/podcasts/podcasting-made-simple-alex-sanfilippo-W9LpyfDm5vn-eqKdimAPJzr.1400x1400.jpg',
    '<p>Podcasting Made Simple is the premier podcast about podcasting! We’re here to help podcast guests and podcast hosts reach more listeners and grow their income so they can change more lives! Join Alex Sanfilippo and other podcasting industry experts as they share how you can level up on either side of the mic! (Show notes and resources: <a href="https://www.google.com/url?q=https://PodMatch.com/episodes&amp;sa=D&amp;source=calendar&amp;usd=2&amp;usg=AOvVaw2fxySkCm7jyQwPr_3js39A">https://PodMatch.com/episodes</a>)</p>'
) ON CONFLICT (podcast_id) DO UPDATE SET
    priority = EXCLUDED.priority,
    title = EXCLUDED.title,
    publisher = EXCLUDED.publisher,
    image_url = EXCLUDED.image_url,
    description = EXCLUDED.description,
    updated_at = NOW();
INSERT INTO featured_podcasts (
    podcast_id, 
    priority, 
    title, 
    publisher, 
    image_url, 
    description
) VALUES (
    'fae778ade7d14eb786fa76476a69c807',
    97,
    'The Driven Introvert Podcast',
    'Remi Roy',
    'https://cdn-images-3.listennotes.com/podcasts/the-driven-introvert-podcast-remi-roy-JhB1zj0Fqb9-PIcri-byhLH.1400x1400.jpg',
    '<p>The Driven Introvert is a faith-inspired podcast designed for purposeful introverts. It''s the place to be for dreamers, doers, and entrepreneurs ready to bring to life the dreams, callings, and ideas God has placed in their hearts.<br><br></p><p>Are you holding onto an idea that you''ve been thinking about for a while but are unsure how to start?</p><p>Do you sense that God is calling you to step out and do something new, but fear, uncertainty, or lack of clarity is holding you back?</p><p>Our goal is to help you Get Unstuck, make progress on your God-inspired ideas, and find a supportive community.</p><p><br></p><p>On this bi-weekly show, host Remi Roy, founder of Shepact.com, offers unique perspectives on what it means to follow dreams, passionately build out ideas, and live a life that matters. Tune in for inspiring conversations, valuable resources, reflective insights, and stories that will remind you that the life and work you''ve envisioned is possible, and your unique personality is not a limitation to achieving it.</p>'
) ON CONFLICT (podcast_id) DO UPDATE SET
    priority = EXCLUDED.priority,
    title = EXCLUDED.title,
    publisher = EXCLUDED.publisher,
    image_url = EXCLUDED.image_url,
    description = EXCLUDED.description,
    updated_at = NOW();
INSERT INTO featured_podcasts (
    podcast_id, 
    priority, 
    title, 
    publisher, 
    image_url, 
    description
) VALUES (
    'e5d104f2103b47e2afa77f663ea88312',
    96,
    'Wickedly Judged ',
    'Rebecca Wall',
    'https://cdn-images-3.listennotes.com/podcasts/wickedly-judged-rebecca-wall-rf2V37gipsl-Govet569ZPI.1400x1400.jpg',
    '<p>What if the system meant to protect us is the one that fails us the most?  Welcome to Wickedly Judged, a true-crime podcast uncovering the flaws, biases, and wrongful convictions hidden within the justice system.  Our first season unpacks the case of Johnny Watkins-an ongoing legal battle that reveals the cracks in the foundation of our courts.  Through deep investigations, expert interviews, and firsthand accounts, we expose the truth behind wrongful convictions and the fight for justice.  Subscribe now and join us as we uncover the real cost of injustice.</p>'
) ON CONFLICT (podcast_id) DO UPDATE SET
    priority = EXCLUDED.priority,
    title = EXCLUDED.title,
    publisher = EXCLUDED.publisher,
    image_url = EXCLUDED.image_url,
    description = EXCLUDED.description,
    updated_at = NOW();
INSERT INTO featured_podcasts (
    podcast_id, 
    priority, 
    title, 
    publisher, 
    image_url, 
    description
) VALUES (
    '4795865feba9458f9d10a0a3e59664bd',
    95,
    'The Jasmine Star Show',
    'Jasmine Star',
    'https://cdn-images-3.listennotes.com/podcasts/the-jasmine-star-show-jasmine-star-fOGqN8wHXDc-fIg0z-X1_ed.1400x1400.jpg',
    '<p>The Jasmine Star Show is a conversational business podcast that explores what it really means to turn your passion into profits. Law school dropout turned world-renowned photographer and expert business strategist, host Jasmine Star delivers her best business advice every week with a mixture of inspiration, wittiness, and a kick in the pants. On The Jasmine Star Show, you can expect raw business coaching sessions, honest conversations with industry peers, and most importantly: tactical tips and a step-by-step plan to empower entrepreneurs to build a brand, market it on social media, and create a life they love.</p>'
) ON CONFLICT (podcast_id) DO UPDATE SET
    priority = EXCLUDED.priority,
    title = EXCLUDED.title,
    publisher = EXCLUDED.publisher,
    image_url = EXCLUDED.image_url,
    description = EXCLUDED.description,
    updated_at = NOW();
INSERT INTO featured_podcasts (
    podcast_id, 
    priority, 
    title, 
    publisher, 
    image_url, 
    description
) VALUES (
    'd4ccd46fb088469284dbf8c23c92a233',
    94,
    'Honest Christian Conversations',
    'Ana Murby',
    'https://cdn-images-3.listennotes.com/podcasts/honest-christian-conversations-ana-murby-TyhgKtdqAmN-J7ozgtc5sXu.1400x1400.jpg',
    '<p>A weekly podcast dealing with cultural and spiritual issues within the Christian faith.&nbsp;</p>'
) ON CONFLICT (podcast_id) DO UPDATE SET
    priority = EXCLUDED.priority,
    title = EXCLUDED.title,
    publisher = EXCLUDED.publisher,
    image_url = EXCLUDED.image_url,
    description = EXCLUDED.description,
    updated_at = NOW();
INSERT INTO featured_podcasts (
    podcast_id, 
    priority, 
    title, 
    publisher, 
    image_url, 
    description
) VALUES (
    'b9aac41c6f134a00ab4d26f47bba30b5',
    93,
    'One on One with Mista Yu',
    'Mista Yu',
    'https://cdn-images-3.listennotes.com/podcasts/one-on-one-with-mista-yu-mista-yu-KaAOsMtUn39-b42DJlSTP8r.1400x1400.jpg',
    '<p><b>Real talk, hard sayings, and authentic conversations from game changers and excuse removers worldwide, giving you tools and strategies to help you grow you!</b></p><p><br></p><p>Our flagship show is the most popular on our brand and it’s because we get to talk to the most interesting people from around the world and hear compelling stories of courage, resilience, overcoming abuse, and massive amounts of encouragement that is sure to remove excuses and brighten your day!</p><p><br></p><p>We’re talking to: <b>The Transformational Builder - they’re growth-minded, purpose-driven, and desire continuous improvement. The TCMMY brand helps sharpen their performance in business, ministry, and community, deepen their purpose in their every day lives, and locate authentic connection and lasting impact.</b></p><p><br></p><p>Have a question for or want to get a shoutout from the show? Text the show and Mista Yu will answer it personally. <a href="https://www.buzzsprout.com/twilio/text_messages/1222796/open_sms">https://www.buzzsprout.com/twilio/text_messages/1222796/open_sms</a></p><p><br></p><p>Want to be a guest on our interview show "One On One with Mista Yu"? Send Mista Yu a message on PodMatch here: https://www.podmatch.com/hostdetailpreview/</p><p>theycallmemistayu</p><p><br></p><p>Interested in joining the Podmatch community and becoming a guest on some of the best podcasts in the world? Feel free to use my link: <a href="https://www.joinpodmatch.com/theycallmemistayu">https://www.joinpodmatch.com/theycallmemistayu</a></p><p><br></p><p>🎙️ New to streaming or looking to level up? Check out StreamYard and get $10 discount! 😍 https://streamyard.com/pal/d/4645458557403136</p><p><br></p><p><a href="https://www.buzzsprout.com/?referrer_id=1181885">https://www.buzzsprout.com/?referrer_id=1181885</a></p><p>I trust this host. You will too! Start for FREE</p><p><br>Thank you for listening and following on all listening platforms and social media. You can find all of our social media links here: https://theycallmemistayu.buzzsprout.com&nbsp;</p><p><br></p><p>COFFEE AFICIONADOS AND HEALTH-CONSCIOUS LISTENERS, our show has some new sponsors and they’re offering you the best discounts their stores have (Trust me! I’ve checked).&nbsp;</p><p><br></p><p>Click on these links and start saving on some really incredible products:</p><p><br></p><p>Quantum Squares: <a href="https://quantumsquares.com/discount/TCMMY">https://quantumsquares.com/discount/TCMMY</a></p><p><br></p><p>Strong Coffee: <a href="https://strongcoffeecompany.com/discount/TCMMY">https://strongcoffeecompany.com/discount/TCMMY</a></p><p><br></p><p>ZivoLife: <a href="https://zivo.life/discount/TCMMY">https://zivo.life/discount/TCMMY</a></p><p><br></p><p>****Please note : There are multiple dates during the month of July, August, November, and December where there will be a break in recording and interviews.****</p>'
) ON CONFLICT (podcast_id) DO UPDATE SET
    priority = EXCLUDED.priority,
    title = EXCLUDED.title,
    publisher = EXCLUDED.publisher,
    image_url = EXCLUDED.image_url,
    description = EXCLUDED.description,
    updated_at = NOW();
INSERT INTO featured_podcasts (
    podcast_id, 
    priority, 
    title, 
    publisher, 
    image_url, 
    description
) VALUES (
    '8eb09c87751d46e4b65d042c8685d8d7',
    92,
    'Channel 15 Radio dot com',
    'Multiple Artists',
    'https://cdn-images-3.listennotes.com/podcasts/channel-15-radio-dot-com-multiple-artists-FUOBev7cNGE-lRrBjQkpGVx.1400x1400.jpg',
    '<p>Welcome to Channel 15 Radio dot com. Old time radio drama for a new era. Our&nbsp; feature audio drama is THE AMBASSADOR, a fun, family-friendly, sci-fi, martial arts adventure.&nbsp;<br><br>The Ambassador is a highly respected older woman, not another Captain or Lost Renegade. She is not a broken relic looking for redemption. She’s good at what she does. Very good. She is slightly snarky, really likes coffee, is an adept in the martial arts, speaks multiple languages, and keeps lots of secrets. She’s still got game but she’s not a ‘young vixen’ any more. She’d like to retire. She can’t. The High Council has summoned her for a difficult new mission.&nbsp;<br><br></p><p>The Ambassador and her team don’t save the universe. They try to do good. Sometimes they succeed. Sometimes they fail. They are excellent at what they do. They are brilliant and humble, honest and kind. They are mostly regular, normal, outwardly average, incredibly interesting, quietly extraordinary people.&nbsp;</p>'
) ON CONFLICT (podcast_id) DO UPDATE SET
    priority = EXCLUDED.priority,
    title = EXCLUDED.title,
    publisher = EXCLUDED.publisher,
    image_url = EXCLUDED.image_url,
    description = EXCLUDED.description,
    updated_at = NOW();
INSERT INTO featured_podcasts (
    podcast_id, 
    priority, 
    title, 
    publisher, 
    image_url, 
    description
) VALUES (
    'fb6b7fad0e294184b8c9c9c7256283f2',
    91,
    'Behind the Workflow',
    'Simona Costantini and Taly Melo',
    'https://cdn-images-3.listennotes.com/podcasts/behind-the-workflow-tvo6GPL3XAy-pXRge1os6U4.1400x1400.jpg',
    'Looking for expert insights on how to streamline, scale, and optimize your content production? You’re in the right place! Behind the Workflow is your go-to resource for podcast networks, agencies, content creators, and YouTubers who want to refine their workflows, improve efficiency, and keep their production running smoothly.

Hosted by Simona Costantini and Taly Melo, this show dives into everything you need to know—from managing client workflows and scaling production to leveraging the best tools in the industry. Whether you’re a solo podcast manager, a content creator juggling multiple platforms, or running a full-scale agency, you’ll find actionable insights that help you work smarter, not harder.

Each episode breaks down key strategies for burning questions like:

How do podcast networks, agencies, and content creators keep their operations organized and efficient?

What are the best systems for managing multiple shows, clients, and content platforms without stress?

How can I streamline my workflow to save time and increase productivity?

What tools and software should I be using to optimize my podcast and video production?

How do successful agencies, YouTubers, and content managers scale their services while maintaining quality?

This show isn’t about vague advice or unnecessary fluff—it’s all about real-world strategies, expert guidance, and proven techniques to help you simplify your process and focus on what matters. Through each conversations, you’ll gain exclusive behind-the-scenes insights into how top-tier professionals stay ahead in the ever-evolving podcasting and content creation industry.

Tune in every other week as we cover everything from workflow automation, content planning, and video production to industry trends and client management. Plus, get access to insider tips and resources you won’t find anywhere else, so you can stay ahead of the game.

🚀 Brought to you by Northflow—the platform helping creators, podcast managers, and agencies refine their production process.

Subscribe now and take your podcast and content production to the next level!'
) ON CONFLICT (podcast_id) DO UPDATE SET
    priority = EXCLUDED.priority,
    title = EXCLUDED.title,
    publisher = EXCLUDED.publisher,
    image_url = EXCLUDED.image_url,
    description = EXCLUDED.description,
    updated_at = NOW();
INSERT INTO featured_podcasts (
    podcast_id, 
    priority, 
    title, 
    publisher, 
    image_url, 
    description
) VALUES (
    'd339da5cb77d43e49868eb0a4677397a',
    90,
    'Blessed + Bossed Up',
    'Anchored Media Network',
    'https://cdn-images-3.listennotes.com/podcasts/blessed-bossed-up-anchored-media-network-jZnrN7PiS-e--ITvbKuhOUf.1400x1400.jpg',
    '<p>The BBU Podcast is a weekly podcast that teaches purposeful women how to be uncompromising in their faith, business, and total life success with God as the CEO. Get ready to be empowered, emboldened, and receive divine strategy to fulfill God’s plan for your life and business. Your host + sister in Christ and success, Tatum Temia Ayomike, is an award-winning entrepreneur, executive producer, author and devoted Christian who has committed her life to help women bridge the gap between faith and business. Her impact as the CEO of Anchored Media includes a global reach of millions of listeners across 75+ produced podcast shows in just 2 years. Through her personal brand, Tatum has cultivated a community of businesswomen who give God full authority to use their business as a vessel for the Kingdom. Using the word of God as her platform, Tatum&#39;s prayer journal and published books offer instrumental guidance to ‘boss up’ in any entrepreneurial venture. Tatum has been featured in several magazines and publications and has been named as a Top 30 under 30 in the Washington, DC area.</p>'
) ON CONFLICT (podcast_id) DO UPDATE SET
    priority = EXCLUDED.priority,
    title = EXCLUDED.title,
    publisher = EXCLUDED.publisher,
    image_url = EXCLUDED.image_url,
    description = EXCLUDED.description,
    updated_at = NOW();
INSERT INTO featured_podcasts (
    podcast_id, 
    priority, 
    title, 
    publisher, 
    image_url, 
    description
) VALUES (
    '0376121666a04bc783b8979b36f8f229',
    89,
    'Podcasting for Solopreneurs | Podcasting Tips and Online Marketing Strategies for Business Growth',
    'Julia Levine | Podcasting Coach for Business Growth (The Podcast Teacher™)',
    'https://cdn-images-3.listennotes.com/podcasts/podcasting-for-solopreneurs-podcasting-tips-Ou6ToAwSe7x-dYmuiXQ7ofP.1400x1400.jpg',
    '<p>Are you a business owner looking for podcasting and online marketing tips to grow your show and convert listeners into sales? This podcast about how to podcast has you covered!</p><p><br></p><p>You’ll get actionable strategies to increase your downloads, attract new listeners, and ultimately convert those listeners into sales for your online business.</p><p><br></p><p>Your host, Julia Levine, also known as The Podcast Teacher™, is a fellow solopreneur as well as a certified podcast growth coach.&nbsp;</p><p><br></p><p>She shares her podcasting expertise to help you leverage your podcast to build authority in your niche, expand your reach, and grow your client base.</p><p><br></p><p>With over 10 years of experience as an educator, Julia combined her passion for teaching with her love for podcasting to create a show that delivers real results. This show has ranked in the top 25 on Apple Podcasts in 8 different countries, placing it in the top 1.5% of all podcasts worldwide.&nbsp;</p><p><br></p><p>Now, she’s teaching you the proven podcasting growth strategies that helped her achieve that success so you can do the same with your podcast!</p><p><br></p><p>In this podcast about podcasting, solopreneurs will learn podcasting tips to answer questions like:&nbsp;</p><p>-How can I get more podcast listeners and grow my audience?</p><p>-How do I use a podcast to grow my online business?</p><p>-What are the best ways to promote my podcast as a solopreneur?</p><p>-How do I get more podcast downloads?</p><p>-What are podcasting growth strategies?</p><p>-How can I convert podcast listeners into paying clients and customers for my online business?</p><p>-What are the best podcast online marketing strategies?</p><p>-What can I do to improve my podcast’s SEO and discoverability?</p><p><br><br></p><p>New episodes are released every Tuesday and Friday. Be sure to hit that follow button so you never miss out on the podcasting strategies and online marketing tips to grow your show and your business!</p><p><br></p><p>Next Steps:</p><p>Check out the website: www.ThePodcastTeacher.com</p><p>Email Julia: <a href="mailto:Julia@ThePodcastTeacher.com">Julia@ThePodcastTeacher.com</a></p><p><br></p><p>Uncover what''s holding your podcast back and the strategy that <em>you</em> should be focusing on to grow it with the 60-second quiz: www.ThePodcastTeacher.com/quiz</p><p><br></p><p>No Podcast yet? Grab the free Podcast Roadmap: 10 Simple Steps to Launch Your Own Podcast (No Fancy Tech Required!): www.ThePodcastTeacher.com/roadmap</p>'
) ON CONFLICT (podcast_id) DO UPDATE SET
    priority = EXCLUDED.priority,
    title = EXCLUDED.title,
    publisher = EXCLUDED.publisher,
    image_url = EXCLUDED.image_url,
    description = EXCLUDED.description,
    updated_at = NOW();
INSERT INTO featured_podcasts (
    podcast_id, 
    priority, 
    title, 
    publisher, 
    image_url, 
    description
) VALUES (
    '147dc693635f41a38fbed9e582b83ee5',
    88,
    'Grow The Show',
    'Kev Michael',
    'https://cdn-images-3.listennotes.com/podcasts/grow-the-show-kev-michael-tbN8CJ92UuD--EM138OVuCw.1400x1400.jpg',
    'Grow The Show is the podcast that grows YOUR podcast. Hosted by Kev Michael, a full-time podcaster since 2018 and growth coach to over 500 creators. Each episode delivers actionable strategies, real-world coaching, and expert interviews that help you build a bigger audience and turn your podcast into a powerful business asset. With millions of downloads and several million dollars in podcast-driven revenue under his belt, Kev brings the proven playbook for podcasters who are ready to go beyond the hobby and into growth. Subscribe now to learn how to grow your podcast — and make it work for you.'
) ON CONFLICT (podcast_id) DO UPDATE SET
    priority = EXCLUDED.priority,
    title = EXCLUDED.title,
    publisher = EXCLUDED.publisher,
    image_url = EXCLUDED.image_url,
    description = EXCLUDED.description,
    updated_at = NOW();
INSERT INTO featured_podcasts (
    podcast_id, 
    priority, 
    title, 
    publisher, 
    image_url, 
    description
) VALUES (
    '4ebb761f62e34496a5ec64b4787a9b9f',
    87,
    'Start That Business | How to start a business, Service Based Business Online, Freelancing, Make Money Online',
    'Chichi Ukomadu - Christian Business Coach, Implementation Coach, Accountability Coach',
    'https://cdn-images-3.listennotes.com/podcasts/start-that-business-how-to-start-a-business-eTYmGL4XDWI-S8jTZg_eN36.1400x1400.jpg',
    'The Go-to Podcast for Christian women who want to start an online service-based business from scratch!<br /><br />** TOP 2.5% GLOBALLY RANKED CHRISTIAN BUSINESS PODCAST**<br /><br />Are you ready to streamline your focus and get clarity to start your online service-based business?<br />Are you tired of struggling with lack of clarity, self-doubt, and the fear of being a public failure?<br />Do you wish you had a clear plan you could follow to make your calling a reality?<br /><br />Hey Friend! You don’t have to stay stuck any longer. With a renewed mindset and a clear plan, you can start a business that fulfills your calling and makes a profit.<br /><br />I’m Chichi Ukomadu, a Christian business coach, implementation coach, and a seven-figure service-based entrepreneur.<br /><br />In this podcast, I’ll teach you how to:<br />- Streamline your focus<br />- Get clarity on your business idea<br />- Create your business launch plan<br />- Set up your business essentials and<br />- Launch your sustainable and profitable business from scratch<br /><br />You’ll get tons of encouragement, godly wisdom, and accountability to grow in your faith and new business journey.<br /><br />It’s time to partner with God and take your first step to start that business.<br />You know the one I’m talking about.<br />Yes, that one you’ve been putting off for a long time.<br /><br />Next Steps:<br />- Download Business Clarity Blueprint: https://www.startthatbusinesspodcast.com<br />- Book Coaching Session: http://bit.ly/4b5Hq23<br />- Join Free Business Community: https://www.facebook.com/groups/startaservicebasedbusinesscommunity/ <br />- Visit Website: https://www.chichiukomadu.com/ <br />- Email Us: gethelp@chichiukomadu.com'
) ON CONFLICT (podcast_id) DO UPDATE SET
    priority = EXCLUDED.priority,
    title = EXCLUDED.title,
    publisher = EXCLUDED.publisher,
    image_url = EXCLUDED.image_url,
    description = EXCLUDED.description,
    updated_at = NOW();
INSERT INTO featured_podcasts (
    podcast_id, 
    priority, 
    title, 
    publisher, 
    image_url, 
    description
) VALUES (
    '86b234eab6784e06a9bda1d020d20f1e',
    86,
    'As It Relates to Podcasting with Simona Costantini',
    'Simona Costantini',
    'https://cdn-images-3.listennotes.com/podcasts/as-it-relates-to-podcasting-simona-costantini-eLsFpjOXlvg-J0vDh6qn_Aj.1400x1400.jpg',
    'Looking for expert tips on how to launch, grow, and monetize your podcast? You’re in the right place! As It Relates to Podcasting is your go-to resource for entrepreneurs, business owners, content creators, coaches, and consultants who want to leverage podcasting to build their brand, boost their business, and create meaningful connections with their audience.

Hosted by full-time podcast strategist and producer Simona Costantini, this show dives into everything you need to know—from successfully starting your podcast to growing your listener base and turning your show into a revenue-generating machine. Whether you’re looking to optimize your strategy or hitting record for the first time, you’ll find practical insights that cut through the noise.

Each episode breaks down actionable strategies for burning questions like:
- How do I successfully launch my podcast and stand out from the crowd?
- What are the most effective ways to increase my downloads and grow my audience?
- How can I monetize my podcast without overwhelming my listeners?
- What steps should I take to attract sponsors, partners, and collaborations?
- How can I use my podcast to drive clients, customers, and revenue for my business?
- What are the best tools and systems for running a smooth, stress-free podcast?

This show isn’t about fluff or recycled advice—it’s all about providing real-world tips, tested strategies, and expert guidance to help you avoid burnout, stay consistent, and scale your podcast into a successful platform. Through solo episodes and deep-dive roundtables, you’ll gain access to insider knowledge that helps you sidestep common podcast pitfalls and maximize your impact.

Tune in weekly as we cover everything from content creation and audience engagement to advanced marketing tactics and monetization methods that actually work. Plus, get exclusive backstage access to tips and resources you won’t find anywhere else, so you can fast-track your growth and start seeing results.

Subscribe now and take the next step in turning your passion for podcasting into a profitable venture that reaches and resonates with your ideal audience!'
) ON CONFLICT (podcast_id) DO UPDATE SET
    priority = EXCLUDED.priority,
    title = EXCLUDED.title,
    publisher = EXCLUDED.publisher,
    image_url = EXCLUDED.image_url,
    description = EXCLUDED.description,
    updated_at = NOW();
INSERT INTO featured_podcasts (
    podcast_id, 
    priority, 
    title, 
    publisher, 
    image_url, 
    description
) VALUES (
    '99befe38324f441596efadb4850d28e4',
    85,
    'Creator Factor with Ozeal ',
    'Ozeal',
    'https://cdn-images-3.listennotes.com/podcasts/creator-factor-with-ozeal-ozeal-Ps6k0vKe39a-DVizInFkYp9.1400x1400.jpg',
    '<p>I''m Ozeal, a community builder and host of Creator Factor, a show dedicated to helping business-minded creators navigate the world of content creation, monetization strategies, content marketing, and entrepreneurship. I started this podcast to help creators grow, monetize their message, and live their best lives while succeeding in the creator economy.</p><p><br></p><p>I believe creators are the new entrepreneurs and community leaders of the business world. My mission is to provide the latest resources, tools, and strategies to help creators succeed in this exciting new era of online entrepreneurship.</p><p><br></p><p>Join me every Wednesday as I have conversations with thought leaders, creative professionals, and everyday creators who are building their brands, growing their audiences, and transforming their businesses. We dive into personal branding, entrepreneurial mindset, and proven business strategies that are driving success in the creator space.</p><p><br></p><p>New episodes drop every Wednesday. Your support means the world to me—click the follow button and leave a review to help spread the love with Creator Factor. I can''t wait for you to join us on this journey and let us help empower your Creator Factor.</p><p><br></p><p>Visit <a href="https://creatorfactor.net/">https://creatorfactor.net</a> to learn more and become part of our ever-growing tribe of entrepreneurs and content creators.</p><p><br></p>'
) ON CONFLICT (podcast_id) DO UPDATE SET
    priority = EXCLUDED.priority,
    title = EXCLUDED.title,
    publisher = EXCLUDED.publisher,
    image_url = EXCLUDED.image_url,
    description = EXCLUDED.description,
    updated_at = NOW();
INSERT INTO featured_podcasts (
    podcast_id, 
    priority, 
    title, 
    publisher, 
    image_url, 
    description
) VALUES (
    'da12362ba05c4db8aabf05fef9cf2b3f',
    84,
    'Friendly Podcast Guide: Teaching Women How to Grow a Podcast (Without Burning Out)',
    'Andi Smiley',
    'https://cdn-images-3.listennotes.com/podcasts/the-friendly-podcast-guide-andi-smiley-leaZ_zRKuUt-IzA2EPRKmwD.1400x1400.jpg',
    'Hey, I’m Andi Smiley, your Friendly Podcast Guide and podcast coach for women! After 6 years in the podcasting world, I know how to help you start a successful podcast as a woman and mom, grow your podcast audience, and actually enjoy the process. On this show, you’ll get podcasting for beginners made simple, podcast tips for women, and sustainable podcast marketing strategies—so you can build a podcast you love without the burnout.
'
) ON CONFLICT (podcast_id) DO UPDATE SET
    priority = EXCLUDED.priority,
    title = EXCLUDED.title,
    publisher = EXCLUDED.publisher,
    image_url = EXCLUDED.image_url,
    description = EXCLUDED.description,
    updated_at = NOW();
INSERT INTO featured_podcasts (
    podcast_id, 
    priority, 
    title, 
    publisher, 
    image_url, 
    description
) VALUES (
    '69d14f55c3604b32a3abb9ccc55e24cf',
    83,
    'Dallas, Texas: What’s Good? Lessons from your Local Entrepreneurs and Small Business Owners',
    'Brianna Jovahn',
    'https://cdn-images-3.listennotes.com/podcasts/dallas-texas-whats-good-lessons-from-your-DB5FNxWXvEn-ungMK9pG0_3.1400x1400.jpg',
    'What''s Good brings you inspiring conversations with Dallas entrepreneurs and creatives, diving deep into their journeys, lessons learned, and successes. Discover the unique culture and spirit of Dallas business with stories that highlight resilience, growth, and innovation in the local community. Perfect for anyone interested in business insights, entrepreneurial tips, and stories that celebrate the people driving Dallas forward.

In each episode, you’ll learn answers to questions like:
• What’s it like to be an entrepreneur in Dallas?
• How do Dallas creatives and entrepreneurs build their brands?
• What are the challenges and rewards of running a business in Dallas?
• What advice do local entrepreneurs have for starting a business?
• How can I find inspiration from successful business owners?
• What are common traits of successful entrepreneurs?
• How does the Dallas business community support local innovation?
• What are some practical tips for networking and growth?
• How do business owners in Dallas stay resilient through challenges?
• What unique opportunities exist for Dallas creatives and business owners?
• What resources are available for the Dallas local community to build a successful business?

Don''t forget to Follow, Share, Rate, and Review!'
) ON CONFLICT (podcast_id) DO UPDATE SET
    priority = EXCLUDED.priority,
    title = EXCLUDED.title,
    publisher = EXCLUDED.publisher,
    image_url = EXCLUDED.image_url,
    description = EXCLUDED.description,
    updated_at = NOW();