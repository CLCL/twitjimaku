#!/usr/bin/perl
 
use version; our $VERSION = qv('0.0.1');
use EV;
use Mojolicious::Lite;
use Mojo::JSON;
use Mojo::IOLoop;
use AnyEvent::Twitter::Stream;
use utf8;
use YAML;
binmode STDOUT => ':utf8';

# コピペ from https://github.com/SetupRu/mojox-transaction-websocket76/blob/master/examples/websocket.pl
use MojoX::Transaction::WebSocket76;
BEGIN {
  use Mojo::Transaction::HTTP ();
  use MojoX::Transaction::WebSocket76 ();

  # Override Mojo::Transaction::HTTP::server_read().
  *Mojo::Transaction::HTTP::server_read = sub {
    my ($self, $chunk) = @_;

    # Parse
    my $req = $self->req;
    $req->parse($chunk) unless $req->error;
    $self->{state} ||= 'read';

    # Parser error
    my $res = $self->res;
    if ($req->error && !$self->{handled}++) {
      $self->emit('request');
      $res->headers->connection('close');
    }

    # EOF
    elsif ((length $chunk == 0) || ($req->is_finished && !$self->{handled}++)) {
      if (lc($req->headers->upgrade || '') eq 'websocket') {
        # Upgrade to WebSocket of needed version.
        $self->emit(upgrade =>
            ($req->headers->header('Sec-WebSocket-Key1')
          && $req->headers->header('Sec-WebSocket-Key2'))
            ? MojoX::Transaction::WebSocket76->new(handshake => $self)
            : Mojo::Transaction::WebSocket->new(handshake => $self)
        );
      }
      $self->emit('request');
    }

    # Expect 100 Continue
    elsif ($req->content->is_parsing_body && !defined $self->{continued}) {
      if (($req->headers->expect || '') =~ /100-continue/i) {
        $self->{state} = 'write';
        $res->code(100);
        $self->{continued} = 0;
      }
    }
  };
}
# MojoX::Transaction::WebSocket76 によるオーバーライド ここまで
plugin 'charset' => {charset => 'UTF-8'};
my $config = plugin 'Config'; 

# Mojoliciousサーバに接続されたクライアント（グローバル変数：Mojoliciousと
# AnyEventイベントリスナーで共有します。）
my $clients = {};

# AnyEvent リスナー設定（グローバル：お互いのイベントリスナー内部から操作する必要がある）
my $listener_twitter; # AnyEvent::Twitter::Streamのイベントリスナー
my $listener_timer;   # AnyEventのTimerのイベントリスナー
my $set_timer; # $set_twitter内で$set_timerを書くのでここで宣言しておく必要がある

my $keys = YAML::LoadFile( app->home->rel_file('twitter_keys.yaml') );
# consumer_keyなど読込はdebugモードのエラー画面でstashに乗っかるのでPlugin 'Config'には入れない
# index.cgiと同じディレクトリにtwitter_keys.yaml ファイルを以下の形式で置いておく
# 同じディレクトリだとHTTPアクセスで鍵漏れするので、【HTTPでアクセスできないところに
# 置かなくてはならない】このサンプルはわかりやすさ優先のため同じディレクトリにおいている
# また.htaccessなどで一応HTTPで読み込めないよう指定をしているが設置者の自己責任で。
# キーはTwitterにDevelopper登録して、自分で取得する必要がある。
# "consumer_key" : 'aaaaaaaaaaaaaaaaaaa'
# "consumer_key_secret" : 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
# "access_token"        : 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
# "access_token_secret" : 'yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy'

app->secret($keys->{consumer_key}); # アプリ固有の暗号キーをTwitterのKey流用

# AnyEvent::Twitter::Streamの設定
my $set_twitter = sub {
  $listener_twitter = AnyEvent::Twitter::Stream->new(
    consumer_key    => $keys->{consumer_key},
    consumer_secret => $keys->{consumer_key_secret},
    token           => $keys->{access_token},
    token_secret    => $keys->{access_token_secret},
    # methodは下の3つより選択する
    method => 'sample',      # sampleストリーム
    #method => 'userstream', # ユーザストリーム
    #method => 'filter', track  => 'perl', # キーワードフィルタ
    on_tweet => sub {
      my $tweet = shift; # $tweetはflagged utf8
      # $dropretioの分だけ不採用
      #my $dropretio = 0;   # 捨てません。
      my $dropretio = 0.90; # 9割捨てます。sample
      # sample streamは流量多いので指定するとよい
      return if rand(1) < $dropretio;
      my $user = $tweet->{user}{screen_name};
      my $text = $tweet->{text} || '';
      my $lang = $tweet->{user}{lang} || '';
      return if $lang ne 'ja'; # 日本語のみ
      return unless $user && $text; # たまに空のTweetが流れるのを防ぐ
      $text =~ s/[\x00-\x1f\x7f]//g; # コントロールコード除去
      $text =~ s/&lt;/</g;
      $text =~ s/&gt;/>/g;
      # 伏せ字処理
      # 注意：Twitterのレギュレーションだとツイート改変は禁止なので、
      # 実運用では公開範囲を限定して伏せ字は使わない方がよいです
      my $censor = sub {
        # ユーザー名を伏せ字
        $user =~ s/./*/g;
        # ツイート内容の名前らしきところを伏せ字＆撹乱
        $text =~ s/\@[^\s:]+/@****/g;
        $text =~ s/[^\s]+さん/****ちゃん/g;
        $text =~ s/[^\s]+ちゃん/****さん/g;
        $text =~ s/[^\s]+くん/****クン/g;
        # URLを伏せ字
        $text =~ s{http://t.co/[\w\-]+}{http://t.co/******}g;
      };
      $censor->(); # 伏せ字しないときはコメントアウトすること
      print "$user : $text\n"; # コンソールに表示
      # JSONに変換
      my $json = Mojo::JSON->new;
      my $str = $json->encode({ user => $user, text => $text, });
      # Mojo::JSONするとutf8 frag落ちるのでutf8 fraggedにする
      utf8::decode( $str );
      # Mojoliciousサーバに接続中の全てのクライアントに送信
      # ややこしいのですが、WebSocketのコネクションは、Mojoliciousで
      # 用意してくれていて、$clientから操作できます。
      for (keys %$clients) { # $_にkeyが暗黙的に入ります
        # WebSocketで一つのクライアントにメッセージ送信via Mojolicious
        $clients->{$_}->send( $str );
      }
    },
    # AnyEvent::Twitter::Stream 接続エラー
    on_error => sub {
      my $error = shift;
      warn "ERROR: $error";
      undef $listener_twitter; # AnyEvent::Twitter::Streamのイベントリスナーいったん消去
      undef $listener_timer;   # AnyEventのTimerイベントリスナーいったん消去
      $set_timer->(5); # AnyEventのTimerでAnyEvent::Twitter::Streamのイベントリスナー作り直す
    },
    on_eof   => sub {
    },
  );
};

# AnyEventのタイマーイベント（AnyEvent::Twitter::Streamの接続監視・再接続用）
# 引数の分だけ待ったあと、AnyEvent::Twitter::Streamのリスナーの存在監視をします。
# AnyEvent::Twitter::Streamのリスナーでは接続が切れたとき、自身から再接続の手続
# きが出来ないので、別のイベントリスナーが監視して再接続をします。
# あらかじめ宣言する必要があったので、ここではmyを付けずに代入
$set_timer = sub {
  my $after = shift || 0;
  $listener_timer = AnyEvent->timer(
     after    => $after,
     interval => 10,
     cb => sub {
       unless ( $listener_twitter ) {
         $set_twitter->();
         app->log->debug("AnyEvent_Timer:(re)connecting");
       }
     },
  );
};
  
# Mojolicious::Liteのデスパッチ指定：/（サイトルート：HTML+JSを送信）
get '/' => 'index';
 
# Mojolicious::Liteのデスパッチ指定：/stream（WebSocket通信用エンドポイント）
websocket '/stream' => sub {
  my $self = shift;
  # WebSocketコネクションタイムアウトを設定（デフォルトは15秒）
  Mojo::IOLoop->stream($self->tx->connection)->timeout(900); 
  # Mojoliciousのデバッグログに接続記録
  app->log->debug(sprintf 'Client connected: %s', $self->tx);
  # $clientsにWebSocketクライアントを追加：$clientはグローバルで、
  # AnyEventのイベントリスナーと共有します。AnyEvent::Twitter::Stream
  # のイベントリスナー内で、$clientをループして全接続元にメッセージ送信します。
  my $id = sprintf "%s", $self->tx; # 接続元区別用のIDを生成します
  $clients->{$id} = $self->tx;
  # WebSocketコネクション切断時処理（共通）

  # WebSocketイベント設定（Mojolicious 2以降の書き方。Web上の情報に注意）
  $self->on(
    # message: クライアントからWebSocketでメッセージが到着したときに呼ばれます
    message => sub {}, # 今回はクライアントからは特に受信しないので空っぽです
    # finish: WebSocket通信が終わったときに呼ばれます。
    finish  => sub {
      # ログに切断記録
      app->log->debug('Client disconnected');
      # $clientsからWebSocketクライアントを削除
      delete $clients->{$id};
    },
  );
};
# Mojolicious::Liteのイベントループ開始
$set_timer->();
app->start;
 
__DATA__
@@ index.html.ep
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Mojolicious + WebSocket + Twitter Streaming API</title>
    %= stylesheet begin
    html, body {
      margin: 0px;
      height: 100%;
    }
    % end
  </head>
  <body>
    <div id="enchant-stage"></div>
    %= javascript '/enchant.js';
    %= javascript begin
/* -----------------
ここからenchant.js
----------------- */

enchant();

var SEC = 15;  // 字幕がステージアウトするまでの秒数
var FPS = 30; // フレームレート
// var SCREEN_WIDTH  = 300;
// var SCREEN_HEIGHT = 300;
var SCREEN_WIDTH  = document.body.clientWidth;
var SCREEN_HEIGHT = document.body.clientHeight;
var JIMAKU_FONTSIZE = Math.floor(Math.min(SCREEN_WIDTH, SCREEN_HEIGHT)/20);
var JIMAKU_STEP = Math.floor(JIMAKU_FONTSIZE * 1.3); // 字幕の縦方向間隔

// FIFOバッファ
var fifo = [];

window.onload = function() {
  // enchant.jsのゲームスクリーン
  var game = new Game(SCREEN_WIDTH, SCREEN_HEIGHT);
  game.fps = FPS; // fsp を 変更

  // シーンを用意
  var scene = game.currentScene;
  scene.backgroundColor = "#222";

  // シーン内にグループを用意
  scene.jimakuGroup = new Group();
  scene.addChild(scene.jimakuGroup);

  // WebSocket受信で呼ばれる処理：FIFOバッファに字幕文字列を入れる
  // このメソッドはenchant.js由来のものではなく、WebSocketから
  // 呼ばれたときにコールされるよう追加したものです。
  scene.onwebsocket = function(textString) {
    // FIFOバッファの末尾に付ける
    fifo.push(textString);
    //fifo.push(textString.slice(0,20) ); // デバッグ用：字幕文字列を20文字までに詰める
    fifo = fifo.slice(-32); // FIFOバッファの容量32個まで
  };
  
  // フレーム進行ごとに呼ばれる処理：字幕表示
  // このメソッドはenchant.jsのフレーム進行ごとに呼ばれます。
  // FIFOバッファの溜まり具合によらず一定の時間間隔で呼ばれます。
  // この中のプログラム実行の途中でもWebSocketからの送信があるので
  // FIFOバッファで緩衝します。
  scene.onenterframe = function() {

    // ＊衝突判定用位置情報記録jimakuPositionを作る
    // 現在画面上にある字幕を取得（位置情報から衝突判定をするため）
    var items = this.jimakuGroup.childNodes;
    // 字幕衝突回避判定探索用jimakuPosition（y座標ごとに分類して現在のJimakuのIDを格納）
    var jimakuPosition = {};
    for ( var i = 0; i < items.length; i++ ) {
      if (typeof jimakuPosition[items[i].y] == "undefined") {
        jimakuPosition[items[i].y] = [];
      }
      jimakuPosition[items[i].y].push({"x": items[i].x, "width": items[i].width});
    }
    
    // ＊FIFOバッファから字幕生成
    // フレーム処理開始時のFIFOバッファの長さ
    var fifoLength = fifo.length;
    // FIFOバッファの内容で字幕を生成
    for (var l = 0; l < fifoLength; l++) {
      var textString = fifo.shift(); // FIFOバッファから先頭項目を抜く 
      // 字幕生成
      var jimaku = new Jimaku({ text: textString }); // Jimakuオブジェクト
      jimaku.x = SCREEN_WIDTH; // 画面右に見切れる位置
      jimaku.y = 0;            // とりあえず一番上に配置
      // 字幕衝突回避判定探索
      for ( var i = 0; i < SCREEN_HEIGHT - JIMAKU_STEP; i += JIMAKU_STEP ) {
        jimaku.y = i; // Jimakuの段目
        var collision = 0;    // 衝突判定フラグ
        if ( typeof jimakuPosition[i] != "undefined" ) {
          // jimakuPosition探索のその段に字幕がある場合
          for ( var j = 0; j < jimakuPosition[i].length; j++) {
            var obj = jimakuPosition[i][j];
            // 字幕はすべて一定の秒数で走り終わるので、衝突判定は、新しい字幕
            // の行く先前方に現時刻で新しい字幕が入るだけのスペースがあるかと
            // いう問題に置き換えられる
            if ( ( SCREEN_WIDTH < ( obj.x + obj.width + jimaku.width ) ) ) {
              collision = 1; // 他の字幕とぶつかるのでフラグ立てる
            }
          }
        }
        if ( collision != 1 ) { // その段で他の字幕とぶつからなさそう
          break; // 探索終了、その段に入る
        }
      }
      // 探索ループ終わり、字幕を追加（たいていはbreakで抜けてくる）
      this.jimakuGroup.addChild(jimaku);
      // 探索用jimakuPositionに追加した字幕の位置情報を追加
      if (typeof jimakuPosition[jimaku.y] == "undefined") {
        jimakuPosition[jimaku.y] = [];
      }
      jimakuPosition[jimaku.y].push({"x": jimaku.x, "width": jimaku.width})
    } // FIFOバッファループ終わり
  };

  // Labelクラスを継承したJimakuクラス
  var Jimaku = Class.create(Label, {
    initialize: function(f) {
      Label.call(this);
      this.color = "white";
      this.text  = f.text;
      this.font  = JIMAKU_FONTSIZE + "px sans-selif";
      this.width =  this._boundWidth; // Labelの実際の幅を文字幅に設定する
      // すべての字幕は指定病数内でステージインして、ステージアウトする
      this.speed = ( this.width * 2 + SCREEN_WIDTH ) / ( SEC * FPS );
    },
    // フレーム毎の処理
    onenterframe: function() {
      // 字幕は、与えられたスピードで左方向にちょっとずつ進む
      this.x -= this.speed;
      // 字幕を退場させる処理
      if (this.x < -this.width) { // 字幕退場は、ステージから見切れた時
        this.parentNode.removeChild(this); // お逝きなさい
      }
    }
  });
  
  game.start(); // enchant.js の初期化／イベントループ開始

  /* -----------------
  ここからWebSocket
  ------------------*/
  
  // リコネクション用に名前付き関数にしています
  var wsStart = function() {
    // WebSocketオブジェクト作成（後述のWebSocketオブジェクトで接続）
    var ws = new WebSocket('<%= url_for('stream')->to_abs %>');

    // WebSocket接続時：特に何もしない（ブラウザ内で接続開始がわかるようにすると親切です）
    ws.onopen = function () {
      // ブラウザのデバッグコンソールに接続完了を表示（ブラウザの開発ツールで見られます）
      console.log('WebSocket Connection opened.');
    };
    
    // WebSocketサーバからメッセージ受信：enchant.jsが担当する字幕生成にメッセージを渡す
    ws.onmessage = function (msg) {
      // サーバからメッセージ受け取る
      var res = JSON.parse(msg.data); // JSONオブジェクトはIE8以降
      // 受信データは、res.user, res.textに入っています
      // テロップ流す（下の記述は、res.userは表示に使わない想定です）
      scene.onwebsocket(res.text);
    };
    // WebSocket接続終了時：再接続する：タイムアウトだったり、サーバの再起動だったり
    ws.onclose = function() {
      // ブラウザのデバッグコンソールに接続ロストを表示
      console.log('WebSocket Connection closed.');
      // 再接続するためのウェイト
      setTimeout(
        function() {
          // ブラウザのデバッグコンソールに再接続を表示
          console.log('Reload.');
          //wsStart(); // WebSocket張りなおすのはこちら（JavaScript読み直さない）
          window.location.reload(); // ページリロードする場合はこちら（JSも更新）
        },
        2000 // 2秒の待ち時間
      );
    };
  };
  wsStart(); // WebSocket開始

};

/*---------------------------------
 WebSocketの書き方の違いを吸収する
---------------------------------*/
// Firefox 10まではMozWebSocketだった。
// MozWebSocketが存在するなら、WebSocketオブジェクトをMozWebSocketと同じものにする。
if (typeof MozWebSocket != 'undefined' ) {
  WebSocket = MozWebSocket;
}
    % end

  </body>
</html>
