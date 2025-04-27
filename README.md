# gossip-publisher-zmq
A Core Lightning plugin to publish collected gossip via zmq

## Usage

You need to have a running `bitcoind` instance as well as a running `lightningd` instance.

You might want to consider using the `contrib/startup_regtest.sh` script provided in the [Core Lightning](https://github.com/ElementsProject/lightning.git) repository which provides the `start_ln` script to spin up two Core Lightning nodes using a `regtest bitcoind` backend.

Clone this repository into a folder e. g. `lightning/custom-plugins` using 
```sh
git clone https://github.com/ln-history/gossip-publisher-zmq.git
```

First start the plugin using:
```sh
l1-cli plugin start <absolute-filepath-to-the-plugin>
```

If everything is correctly setup, you will see this response:
```sh
{
   "command": "start",
   "plugins": [
      {
         "name": "/usr/local/libexec/c-lightning/plugins/autoclean",
         "active": true,
         "dynamic": false
      },
      {
         "name": "/usr/local/libexec/c-lightning/plugins/chanbackup",
         "active": true,
         "dynamic": false
      },
      {
         "name": "/usr/local/libexec/c-lightning/plugins/bcli",
         "active": true,
         "dynamic": false
      },
      {
         "name": "/usr/local/libexec/c-lightning/plugins/commando",
         "active": true,
         "dynamic": false
      },
      {
         "name": "/usr/local/libexec/c-lightning/plugins/funder",
         "active": true,
         "dynamic": true
      },
      {
         "name": "/usr/local/libexec/c-lightning/plugins/topology",
         "active": true,
         "dynamic": false
      },
      {
         "name": "/usr/local/libexec/c-lightning/plugins/exposesecret",
         "active": true,
         "dynamic": true
      },
      {
         "name": "/usr/local/libexec/c-lightning/plugins/keysend",
         "active": true,
         "dynamic": false
      },
      {
         "name": "/usr/local/libexec/c-lightning/plugins/offers",
         "active": true,
         "dynamic": true
      },
      {
         "name": "/usr/local/libexec/c-lightning/plugins/pay",
         "active": true,
         "dynamic": true
      },
      {
         "name": "/usr/local/libexec/c-lightning/plugins/recklessrpc",
         "active": true,
         "dynamic": true
      },
      {
         "name": "/usr/local/libexec/c-lightning/plugins/recover",
         "active": true,
         "dynamic": false
      },
      {
         "name": "/usr/local/libexec/c-lightning/plugins/txprepare",
         "active": true,
         "dynamic": true
      },
      {
         "name": "/usr/local/libexec/c-lightning/plugins/cln-renepay",
         "active": true,
         "dynamic": true
      },
      {
         "name": "/usr/local/libexec/c-lightning/plugins/cln-xpay",
         "active": true,
         "dynamic": true
      },
      {
         "name": "/usr/local/libexec/c-lightning/plugins/spenderp",
         "active": true,
         "dynamic": false
      },
      {
         "name": "/usr/local/libexec/c-lightning/plugins/cln-askrene",
         "active": true,
         "dynamic": true
      },
      {
         "name": "/usr/local/libexec/c-lightning/plugins/sql",
         "active": true,
         "dynamic": true
      },
      {
         "name": "/usr/local/libexec/c-lightning/plugins/bookkeeper",
         "active": true,
         "dynamic": false
      },
      {
         "name": "<Absolute-file-path-to-the-plugin>/lightning/custom-plugins/gossip-publisher-zmq/helloworld.py",
         "active": true,
         "dynamic": true
      }
   ]
}
```

Now the plugin is running and be used with the following command:
```sh
l1-cli plugin helloworld
```

You now should see this output:
```sh
{
   "node_id": "<your-node-id>",
   "option": {
      "foo_opt": "bar"
   },
   "cli_params": []
}
```