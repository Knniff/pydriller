# Copyright 2018 Davide Spadini
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
This module includes 1 class, Repository, main class of PyDriller.
"""

import logging
from contextlib import contextmanager
from datetime import datetime
from typing import List, Generator, Union

from pydriller.domain.commit import Commit
from pydriller.git_gp import GitGP
from pydriller.utils.common import open_folder
from pydriller.utils.conf import Conf

logger = logging.getLogger(__name__)


class Repository:
    """
    This is the main class of PyDriller, responsible for running the study.
    """

    def __init__(self, path_to_repo: Union[str, List[str]],
                 single: str = None,
                 since: datetime = None, to: datetime = None,
                 from_commit: str = None, to_commit: str = None,
                 from_tag: str = None, to_tag: str = None,
                 include_refs: bool = False,
                 include_remotes: bool = False,
                 only_in_branch: str = None,
                 only_modifications_with_file_types: List[str] = None,
                 only_no_merge: bool = False,
                 only_authors: List[str] = None,
                 only_commits: List[str] = None,
                 only_releases: bool = False,
                 filepath: str = None,
                 histogram_diff: bool = False,
                 skip_whitespaces: bool = False,
                 clone_repo_to: str = None,
                 order: str = None):
        """
        Init a repository mining. The only required parameter is
        "path_to_repo": to analyze a single repo, pass the absolute path to
        the repo; if you need to analyze more repos, pass a list of absolute
        paths.

        Furthermore, PyDriller supports local and remote repositories: if
        you pass a path to a repo, PyDriller will run the study on that
        repo; if you pass an URL, PyDriller will clone the repo in a
        temporary folder, run the study, and delete the temporary folder.

        :param Union[str,List[str]] path_to_repo: absolute path (or list of
            absolute paths) to the repository(ies) to analyze
        :param str single: hash of a single commit to analyze
        :param datetime since: starting date
        :param datetime to: ending date
        :param str from_commit: starting commit (only if `since` is None)
        :param str to_commit: ending commit (only if `to` is None)
        :param str from_tag: starting the analysis from specified tag (only
            if `since` and `from_commit` are None)
        :param str to_tag: ending the analysis from specified tag (only if
            `to` and `to_commit` are None)
        :param bool include_refs: whether to include refs and HEAD in commit analysis
        :param bool include_remotes: whether to include remote commits in analysis
        :param str only_in_branch: only commits in this branch will be analyzed
        :param List[str] only_modifications_with_file_types: only
            modifications with that file types will be analyzed
        :param bool only_no_merge: if True, merges will not be analyzed
        :param List[str] only_authors: only commits of these authors will be
            analyzed (the check is done on the username, NOT the email)
        :param List[str] only_commits: only these commits will be analyzed
        :param bool only_releases: analyze only tagged commits
        :param bool histogram_diff: add the "--histogram" option when asking for the diff
        :param bool skip_whitespaces: add the "-w" option when asking for the diff
        :param bool clone_repo_to: if the repo under analysis is remote, clone the repo to the specified directory
        :param str filepath: only commits that modified this file will be analyzed
        :param str order: order of commits. It can be one of: 'date-order',
            'author-date-order', 'topo-order', or 'reverse'. Default is reverse.
        """
        file_modification_set = (
            None if only_modifications_with_file_types is None
            else set(only_modifications_with_file_types)
            )
        commit_set = (
            None if only_commits is None
            else set(only_commits)
            )

        options = {
            "git_repo": None,
            "path_to_repo": path_to_repo,
            "from_commit": from_commit,
            "to_commit": to_commit,
            "from_tag": from_tag,
            "to_tag": to_tag,
            "since": since,
            "to": to,
            "single": single,
            "include_refs": include_refs,
            "include_remotes": include_remotes,
            "only_in_branch": only_in_branch,
            "only_modifications_with_file_types": file_modification_set,
            "only_no_merge": only_no_merge,
            "only_authors": only_authors,
            "only_commits": commit_set,
            "only_releases": only_releases,
            "skip_whitespaces": skip_whitespaces,
            "filepath": filepath,
            "filepath_commits": None,
            "tagged_commits": None,
            "histogram": histogram_diff,
            "clone_repo_to": clone_repo_to,
            "order": order
        }
        self._conf = Conf(options)

        # If the user provides a directory where to clone the repositories,
        # make sure we do not delete the directory after the study completes
        self._cleanup = False if clone_repo_to is not None else True

    @contextmanager
    def _prep_repo(self, path_repo: str) -> Generator[GitGP, None, None]:
        with open_folder(path_repo=path_repo,
                         conf=self._conf,
                         cleanup=self._cleanup) as local_path_repo:
            # when multiple repos are given in input, this variable will serve as a reminder
            # of which one we are currently analyzing
            self._conf.set_value('path_to_repo', local_path_repo)

            self.git_repo = GitGP(local_path_repo, self._conf)
            # saving the GitGP object for further use
            self._conf.set_value("git_repo", self.git_repo)

            # checking that the filters are set correctly
            self._conf.sanity_check_filters()
            yield self.git_repo

            # cleaning, this is necessary since GitGP issues on memory leaks
            self._conf.set_value("git_repo", None)
            self.git_repo.clear()
            del self.git_repo

    def traverse_commits(self) -> Generator[Commit, None, None]:
        """
        Analyze all the specified commits (all of them by default), returning
        a generator of commits.
        """
        for path_repo in self._conf.get('path_to_repos'):
            with self._prep_repo(path_repo=path_repo) as git_repo:
                logger.info('Analyzing git repository in %s', git_repo.path)

                # Get the commits that modified the filepath. In this case, we can not use
                # git rev-list since it doesn't have the option --follow, necessary to follow
                # the renames. Hence, we manually call git log instead
                if self._conf.get('filepath') is not None:
                    self._conf.set_value('filepath_commits', git_repo.get_commits_modified_file(self._conf.get('filepath')))

                # Gets only the commits that are tagged
                if self._conf.get('only_releases'):
                    self._conf.set_value('tagged_commits', git_repo.get_tagged_commits())

                # Build the arguments to pass to git rev-list.
                rev, kwargs = self._conf.build_args()

                # Iterate over all the commits returned by git rev-list
                for commit in git_repo.get_list_commits(rev, **kwargs):
                    logger.info('Commit #%s in %s from %s', commit.hash, commit.committer_date, commit.author.name)

                    if self._conf.is_commit_filtered(commit):
                        logger.info('Commit #%s filtered', commit.hash)
                        continue

                    yield commit