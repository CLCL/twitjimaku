#twitjimaku

twitjimakuは、Twitter Stremaing APIからの入力をWebSocketを使ってリアルタイムにウェブブラウザに表示するMojolicious::Liteアプリケーションです。

特徴

* MojoliciousのWebSocketを使ったリアルタイムウェブ表示
* AnyEvent::Twitter::Stream によるTwitterストリームの取り込み
* enchant.jsによる動的表現（ニコニコ動画風字幕）
* MojoX::Transaction::WebSocket76 によるSafari対応
* Android 2.3（Firefox）4.0（Google Chrome）/iOS（Safari）/PC（Opera Firefox Safari）対応
* 今のところ、daemon起動／morbo起動で動きます。
* AnyEventでデータを受信する関係上、CGIでの起動の場合は動かせません。
* hypnotoadではAnyEventまわりで動かないようです。 

##files

設置者が自分で準備し書き換える必要があるファイルは以下の通りです。

* /twitter_keys.yaml : Twitter APIで使うconsumer_keyのペア、access_tokenのペア

##設置

morboで起動させますので、Apache管轄下以外のどこでも置けます。
どのみちCGIでは動かせないので、ApacheのDocumentRoot以下以外に置くことをお勧めします。

##起動

あなたがドメイン example.com のLinuxサーバを持っているなら、設置したディレクトリで

* morbo index.cgi

をしたあと、ブラウザで

* http://example.com:3000/

で黒い画面が表示されれ、字幕が流れます。

[youtube動画](http://www.youtube.com/watch?v=UzbDmQFxOL0)

hypnotoadでは稼働しませんので、サイトに常設しないつもりの設計です。

##changes

* ver 0.0.1 first import
