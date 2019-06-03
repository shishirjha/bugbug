# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

from imblearn.over_sampling import BorderlineSMOTE
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder
from sklearn.svm import LinearSVC

from bugbug import bug_features, bugzilla, feature_cleanup
from bugbug.model import BugCoupleModel

NUM_DUPLICATES = 3000
NUM_DUP_NONDUPS = 2000
NUM_NONDUPS_NONDUPS = 2000

REPORTERS_TO_IGNORE = {"intermittent-bug-filer@mozilla.bugs", "wptsync@mozilla.bugs"}


class LinearSVCWithLabelEncoding(CalibratedClassifierCV):
    def __init__(self, clf):
        super().__init__(clf)
        self._le = LabelEncoder()

    def fit(self, X, y):
        super().fit(X, y)
        self._le.fit(y)


class DuplicateModel(BugCoupleModel):
    def __init__(self, lemmatization=False):
        BugCoupleModel.__init__(self, lemmatization)

        self.sampler = BorderlineSMOTE(random_state=0)
        self.calculate_importance = False

        cleanup_functions = [
            feature_cleanup.responses(),
            feature_cleanup.hex(),
            feature_cleanup.dll(),
            feature_cleanup.fileref(),
            feature_cleanup.url(),
            feature_cleanup.synonyms(),
            feature_cleanup.crash(),
        ]

        self.extraction_pipeline = Pipeline(
            [
                ("bug_extractor", bug_features.BugExtractor([], cleanup_functions)),
                (
                    "union",
                    ColumnTransformer([("text", self.text_vectorizer(), "text")]),
                ),
            ]
        )

        self.clf = LinearSVCWithLabelEncoding(LinearSVC())

    def get_labels(self):
        all_ids = []

        for bug_data in bugzilla.get_bugs():
            if (
                bug_data["creator"] in REPORTERS_TO_IGNORE
                or "dupeme" in bug_data["keywords"]
            ):
                continue

            all_ids.append(bug_data["id"])

        all_ids = set(all_ids)

        classes = {}

        # Only store ids of bugs that have duplicates or are duplicates
        duplicate_ids = []

        duplicates_num = 0
        for bug_data in bugzilla.get_bugs():
            bug_id = bug_data["id"]
            if bug_id not in all_ids:
                continue

            if bug_data["dupe_of"] or len(bug_data["duplicates"]) > 0:
                duplicate_ids.append(bug_id)

            for duplicate_bug_id in bug_data["duplicates"]:
                if duplicate_bug_id not in all_ids:
                    continue

                duplicate_ids.append(duplicate_bug_id)

                if duplicates_num < NUM_DUPLICATES:
                    classes[(bug_id, duplicate_bug_id)] = 1
                duplicates_num += 1

        # Store all remaining ids
        non_duplicate_ids = list(all_ids - set(duplicate_ids))

        print(f"Number of duplicate labels is: {NUM_DUPLICATES}")

        # When the bug has no duplicates, we create dup-nondup labels.
        dup_nondup_num = 0
        for bug_id1 in duplicate_ids:
            for bug_id2 in non_duplicate_ids:
                classes[(bug_id1, bug_id2)] = 0

                dup_nondup_num += 1
                if dup_nondup_num == NUM_DUP_NONDUPS:
                    break

            if dup_nondup_num == NUM_DUP_NONDUPS:
                break

        print(f"Number of hybrid labels is: {NUM_DUP_NONDUPS}")

        # Now we map non-dup to non-dup bug.
        nondup_nondup_num = 0
        for bug_id1 in non_duplicate_ids:
            for bug_id2 in non_duplicate_ids:
                if bug_id1 == bug_id2:
                    continue

                classes[(bug_id1, bug_id2)] = 0

                nondup_nondup_num += 1
                if nondup_nondup_num == NUM_NONDUPS_NONDUPS:
                    break

            if nondup_nondup_num == NUM_NONDUPS_NONDUPS:
                break

        print(f"Number of purely non-duplicate labels is: {NUM_NONDUPS_NONDUPS}")

        return classes, [0, 1]

    def get_feature_names(self):
        return self.extraction_pipeline.named_steps["union"].get_feature_names()