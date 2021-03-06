import io
import re
import json
import logging
import base64

try:
    from urllib.parse import urljoin
except ImportError:
    from urlparse import urljoin

import requests


log = logging.getLogger(__name__)


# log sent requests. received data isn't shown
def enable_requests_debug():
    import http.client

    http.client.HTTPConnection.debuglevel = 1

    log.setLevel(logging.DEBUG)

    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.setLevel(logging.DEBUG)
    requests_log.propagate = True


class File(object):
    def __init__(self, data, enc="ascii"):
        self.name = data["name"]
        self.path = data["path"]
        self.sha = data["sha"]

        content = base64.b64decode(data["content"])
        content = content.decode(enc).strip()
        self.content = content

    def encode_content(self, enc=None):
        data = self.content.encode("ascii")
        data = base64.b64encode(data)
        if enc:
            data = data.decode(enc)

        return data

    def __repr__(self):
        return '<File(path="{}",sha="{}">'.format(self.path, self.sha)


# TODO separate lib?
class Api(object):

    BASE_REST = "https://api.github.com/"
    BASE_GRAPHQL = "https://api.github.com/graphql"
    USER_AGENT = "mcspr/espurna-nightly-builder/builder-v1.0"

    def __init__(self, token):
        self.token = token

        self._http = requests.Session()
        self._http.headers.update(
            {"User-Agent": self.USER_AGENT, "Authorization": "token {}".format(token)}
        )

    def get(self, path, params=None, headers=None):
        url = urljoin(self.BASE_REST, path)
        res = self._http.get(url, params=params, headers=headers)
        return res

    def get_json(self, path, params=None, headers=None):
        return self.get(path, params=params, headers=headers).json()

    def put_json(self, path, data, headers=None):
        url = urljoin(self.BASE_REST, path)
        res = self._http.put(url, json=data, headers=None)
        return res.json()

    def post_json(self, path, data, headers=None):
        url = urljoin(self.BASE_REST, path)
        res = self._http.post(url, json=data, headers=None)
        return res.json()

    def delete(self, path, params=None, headers=None):
        url = urljoin(self.BASE_REST, path)
        res = self._http.delete(url, params=params, headers=headers)
        return res

    def graphql_query(self, query):
        data = json.dumps({"query": query})
        res = self._http.post(self.BASE_GRAPHQL, data=data)
        res = res.json()

        return res


class Repo(object):
    def __init__(self, slug, api):
        self.slug = slug
        self.api = api
        self.base = "repos/{}".format(slug)

        owner, name = slug.split("/")
        self.owner = owner
        self.name = name

    # TODO uritemplate?
    def _base(self, path):
        return "{}/{}".format(self.base, path)

    def tags(self):
        path = self._base("tags")
        res = self.api.get_json(path)
        return res

    @property
    def clone_url(self):
        return "https://github.com/{owner}/{name}.git".format(
            owner=self.owner, name=self.name
        )

    def compare(self, start, end, diff=True):
        path = self._base("compare/{}...{}".format(start, end))

        headers = {}
        if diff:
            headers["Accept"] = "application/vnd.github.VERSION.diff"

        res = self.api.get(path, headers=headers)
        return res.text

    def contents(self, ref, filepath):
        path = self._base("contents/{}".format(filepath))
        res = self.api.get_json(path, params={"ref": ref})
        return res

    def file(self, ref, filepath):
        return File(self.contents(ref, filepath))

    def update_file(self, branch, fileobj, message):
        path = self._base("contents/{}".format(fileobj.path))
        res = self.api.put_json(
            path,
            data={
                "branch": branch,
                "message": message,
                "content": fileobj.encode_content(enc="ascii"),
                "sha": fileobj.sha,
            },
        )
        return (res["content"], res["commit"])

    def delete_tag(self, tagName):
        path = self._base("git/refs/tags/{}".format(tagName))
        res = self.api.delete(path)

        return res.status_code == 204

    def delete_release(self, number):
        path = self._base("releases/{}".format(number))
        res = self.api.delete(path)

        return res.status_code == 204

    def create_release(self, sha, tag, body, name=None, prerelease=False):
        path = self._base("releases")
        data = {
            "tag_name": tag,
            "target_commitish": sha,
            "body": body,
            "prerelease": prerelease,
        }
        if name:
            data["name"] = name

        res = self.api.post_json(path, data)

        return res

    # TODO tag object, not ref. does github display this ever?
    def tag_object(self, commit, name, message):
        path = self._base("git/tags")
        sha = commit["sha"]
        res = self.api.post_json(
            path, {"type": "commit", "tag": name, "object": sha, "message": message}
        )
        return res

    def commit_check_runs(self, sha):
        path = self._base("commits/{}/check-runs".format(sha))
        res = self.api.get_json(path)
        return (res["total_count"], res["check_runs"])

    def branch_head(self, branch):
        path = self._base("branches/{}".format(branch))
        res = self.api.get_json(path)
        return res["commit"]["sha"]

    def releases(self, last=1):
        query = """
        query {
            repository(owner:"OWNER", name:"NAME") {
                releases(last:LAST) {
                    nodes {
                        id
                        url
                        publishedAt
                        tag {
                            name
                            target {
                                oid
                                commitUrl
                            }
                        }
                    }
                }
            }
        }"""
        query = (
            query.replace("OWNER", self.owner)
            .replace("NAME", self.name)
            .replace("LAST", str(last))
            .strip()
        )

        res = self.api.graphql_query(query)
        releases = res["data"]["repository"]["releases"]["nodes"]

        for release in releases:
            # XXX is this reliable?
            id = release["id"]
            del release["id"]
            id = base64.b64decode(id.encode("ascii")).decode("ascii")
            number = id.partition("Release")[-1]
            release["number"] = int(number)

            if release["tag"]:
                sha = release["tag"]["target"]["oid"]
                tag = release["tag"]["name"]
                del release["tag"]
                release["tagName"] = tag
                release["sha"] = sha
            else:
                release["sha"] = None
                release["tagName"] = None

        return releases

    def latest_release(self):
        return self.releases(last=1)[0]


class CommitRange(object):

    RE_BINARY_FILES = re.compile(
        r"^Binary files (?P<source_filename>[^\t\n]+) and (?P<target_filename>[^\t\n]+) differ"
    )
    RE_SOURCE_FILE = re.compile(
        r"^--- (?P<filename>[^\t\n]+)(?:\t(?P<timestamp>[^\n]+))?"
    )
    RE_TARGET_FILE = re.compile(
        r"^\+\+\+ (?P<filename>[^\t\n]+)(?:\t(?P<timestamp>[^\n]+))?"
    )

    def __init__(self, repo, start, end):
        self._repo = repo
        self._start = start
        self._end = end

    @property
    def html_url(self):
        url = "https://github.com/{owner}/{name}/compare/{start}...{end}".format(
            owner=self._repo.owner,
            name=self._repo.name,
            start=self._start,
            end=self._end,
        )
        return url

    def path_changed(self, path_match):
        text = self._repo.compare(self._start, self._end, diff=True)
        stream = io.StringIO(text)

        def git_path(path):
            if path.startswith("a/") or path.startswith("b/"):
                return path[2:]
            return path

        # adapted from unidiff (https://github.com/matiasb/python-unidiff) + binary files support
        for line in stream:
            src_file = self.RE_SOURCE_FILE.match(line)
            if src_file:
                path = git_path(src_file.group("filename"))
                if path.startswith(path_match):
                    return True

            trg_file = self.RE_TARGET_FILE.match(line)
            if trg_file:
                path = git_path(trg_file.group("filename"))
                if path.startswith(path_match):
                    return True

            bin_files = self.RE_BINARY_FILES.match(line)
            if bin_files:
                src = git_path(bin_files.group("source_filename"))
                trg = git_path(bin_files.group("target_filename"))
                if src.startswith(path_match) or trg.startswith(path_match):
                    return True

        return False


# latest release will likely have same commit on both master (release branch) and dev
def release_is_head(repo, head_sha):
    release = repo.latest_release()
    release_sha = release["sha"]

    return release_sha == head_sha
