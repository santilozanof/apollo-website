"""Apollo's static server, with the JSON media type required for Apple's AASA file.

The existing site remains a plain Python static directory. Only the extensionless
association document needs an explicit MIME type; no API routing changes here.
"""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ASSOCIATION = Path('.well-known/apple-app-site-association')


class ApolloStaticHandler(SimpleHTTPRequestHandler):
    def guess_type(self, path):
        if Path(path).resolve() == (Path(self.directory) / ASSOCIATION).resolve():
            return 'application/json'
        return super().guess_type(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--directory', type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    with ThreadingHTTPServer((args.host, args.port), partial(ApolloStaticHandler, directory=str(args.directory))) as server:
        server.serve_forever()


if __name__ == '__main__':
    main()
