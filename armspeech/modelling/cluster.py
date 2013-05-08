"""Clustering algorithms."""

# Copyright 2011, 2012, 2013 Matt Shannon

# This file is part of armspeech.
# See `License` for details of license and warranty.


import dist as d
from armspeech.util.mathhelp import assert_allclose
from armspeech.util.timing import timed
from codedep import codeDeps

import logging
import math
from collections import defaultdict
import itertools
import heapq

@codeDeps()
def partitionLabels(labels, fullQuestion):
    labelValuer, question = fullQuestion
    labelsYes = []
    labelsNo = []
    for label in labels:
        if question(labelValuer(label)):
            labelsYes.append(label)
        else:
            labelsNo.append(label)
    return labelsYes, labelsNo

@codeDeps()
def removeTrivialQuestions(labels, questionGroups):
    if not labels:
        return []
    else:
        questionGroupsOut = []
        for labelValuer, questions in questionGroups:
            questionsOut = []
            for question in questions:
                answerFirst = question(labelValuer(labels[0]))
                trivial = True
                for label in labels:
                    if question(labelValuer(label)) != answerFirst:
                        trivial = False
                        break
                if not trivial:
                    questionsOut.append(question)
            if questionsOut:
                questionGroupsOut.append((labelValuer, questionsOut))
        return questionGroupsOut

@codeDeps(d.addAcc)
class AccSummer(object):
    def __init__(self, accForLabel, createAcc):
        self.accForLabel = accForLabel
        self.createAcc = createAcc

    def sumAccs(self, labels):
        accForLabel = self.accForLabel
        accTot = self.createAcc()
        for label in labels:
            d.addAcc(accTot, accForLabel(label))
        return accTot

    def sumAccsForQuestion(self, labels, fullQuestion):
        labelValuer, question = fullQuestion
        accForLabel = self.accForLabel

        accYes = self.createAcc()
        accNo = self.createAcc()
        for label in labels:
            acc = accForLabel(label)
            if question(labelValuer(label)):
                d.addAcc(accYes, acc)
            else:
                d.addAcc(accNo, acc)

        return accYes, accNo

    def sumAccsFirstLevel(self, labels, questionGroups):
        accForLabel = self.accForLabel
        numQuestionGroups = len(questionGroups)

        labelValuers = [ labelValuer
                         for labelValuer, questions in questionGroups ]
        labelValueToAccs = [ defaultdict(self.createAcc)
                             for _ in range(numQuestionGroups) ]

        for label in labels:
            acc = accForLabel(label)
            for qgIndex in range(numQuestionGroups):
                labelValuer = labelValuers[qgIndex]
                labelValueToAcc = labelValueToAccs[qgIndex]
                d.addAcc(labelValueToAcc[labelValuer(label)], acc)

        # list contains one labelValueToAcc for each questionGroup
        return labelValueToAccs

    def sumAccsSecondLevel(self, labelValueToAcc, question):
        accYes = self.createAcc()
        accNo = self.createAcc()
        for labelValue, acc in labelValueToAcc.iteritems():
            if question(labelValue):
                d.addAcc(accYes, acc)
            else:
                d.addAcc(accNo, acc)

        return accYes, accNo

    def sumAccsForQuestions(self, labels, questionGroups):
        """Returns an iterator with yes and no accs for each question."""
        labelValueToAccs = self.sumAccsFirstLevel(labels, questionGroups)

        for (
            labelValueToAcc, (labelValuer, questions)
        ) in zip(labelValueToAccs, questionGroups):
            for question in questions:
                accYes, accNo = self.sumAccsSecondLevel(labelValueToAcc,
                                                        question)
                fullQuestion = labelValuer, question
                yield fullQuestion, accYes, accNo

    def sumAccsForQuestionGroups(self, labels, questionGroups):
        """Returns an iterator with yes and no accs for each question."""
        labelValueToAccs = self.sumAccsFirstLevel(labels, questionGroups)

        accsForQuestionGroups = []
        for (
            labelValueToAcc, (labelValuer, questions)
        ) in zip(labelValueToAccs, questionGroups):
            accsForQuestions = []
            for question in questions:
                accYes, accNo = self.sumAccsSecondLevel(labelValueToAcc,
                                                        question)
                accsForQuestions.append((question, accYes, accNo))
            accsForQuestionGroups.append((labelValuer, accsForQuestions))

        return accsForQuestionGroups

@codeDeps()
class ProtoLeaf(object):
    def __init__(self, dist, aux, auxRat, count):
        self.dist = dist
        self.aux = aux
        self.auxRat = auxRat
        self.count = count

@codeDeps(ProtoLeaf, d.EstimationError)
class LeafEstimator(object):
    def __init__(self, estimateTotAux):
        self.estimateTotAux = estimateTotAux

    def est(self, acc):
        dist, (aux, auxRat) = self.estimateTotAux(acc)
        count = acc.count()
        return ProtoLeaf(dist, aux, auxRat, count)

    def estOrNone(self, acc):
        try:
            return self.est(acc)
        except d.EstimationError:
            return None

@codeDeps(assert_allclose)
class SplitInfo(object):
    """Collected information for a (potential or actual) split."""
    def __init__(self, protoNoSplit, fullQuestion, protoYes, protoNo):
        self.protoNoSplit = protoNoSplit
        self.fullQuestion = fullQuestion
        self.protoYes = protoYes
        self.protoNo = protoNo

        assert self.protoNoSplit is not None
        if self.fullQuestion is None:
            assert self.protoYes is None and self.protoNo is None
        if self.protoYes is not None and self.protoNo is not None:
            assert_allclose(self.protoYes.count + self.protoNo.count,
                            self.protoNoSplit.count)

    def delta(self):
        """Returns the delta for this split.

        The delta is used to choose which question to use to split a given node
        and to decide whether to split at all.
        """
        if self.protoYes is None or self.protoNo is None:
            return float('-inf')
        else:
            return self.protoYes.aux + self.protoNo.aux - self.protoNoSplit.aux

@codeDeps(SplitInfo)
def maxSplit(protoNoSplit, splitInfos):
    bestSplitInfo = SplitInfo(protoNoSplit, None, None, None)
    for splitInfo in splitInfos:
        if splitInfo.delta() > bestSplitInfo.delta():
            bestSplitInfo = splitInfo
    return bestSplitInfo

@codeDeps()
class Grower(object):
    def allowSplit(self, splitInfo):
        abstract

    def useSplit(self, splitInfo):
        abstract

@codeDeps(Grower)
class SimpleGrower(Grower):
    def __init__(self, thresh, minCount, maxCount = None):
        self.thresh = thresh
        self.minCount = minCount
        self.maxCount = maxCount

        assert self.minCount > 0.0

    def allowSplit(self, splitInfo):
        protoYes = splitInfo.protoYes
        protoNo = splitInfo.protoNo
        return (protoYes is not None and
                protoNo is not None and
                protoYes.count >= self.minCount and
                protoNo.count >= self.minCount)

    def useSplit(self, splitInfo):
        protoNoSplit = splitInfo.protoNoSplit
        allowNoSplit = (self.maxCount is None or
                        protoNoSplit.count <= self.maxCount)

        if splitInfo.fullQuestion is not None and (
            not allowNoSplit or splitInfo.delta() > self.thresh
        ):
            return True
        else:
            if not allowNoSplit:
                assert splitInfo.fullQuestion is None
                logging.warning('not splitting decision tree node even though'
                                ' count = %s > maxCount = %s, since no further'
                                ' splitting allowed' %
                                (protoNoSplit.count, self.maxCount))
            return False

@codeDeps(SimpleGrower)
class ThreshGrowerSpec(object):
    def __init__(self, thresh, minCount, maxCount = None):
        self.thresh = thresh
        self.minCount = minCount
        self.maxCount = maxCount

    def __call__(self, distRoot, countRoot, verbosity = 1):
        return SimpleGrower(self.thresh, self.minCount, self.maxCount)

@codeDeps(SimpleGrower, d.getDefaultParamSpec)
class MdlGrowerSpec(object):
    def __init__(self, mdlFactor, minCount, maxCount = None,
                 paramSpec = d.getDefaultParamSpec()):
        self.mdlFactor = mdlFactor
        self.minCount = minCount
        self.maxCount = maxCount
        self.paramSpec = paramSpec

    def __call__(self, distRoot, countRoot, verbosity = 1):
        numParamsPerLeaf = len(self.paramSpec.params(distRoot))
        thresh = (
            0.5 * self.mdlFactor * numParamsPerLeaf * math.log(countRoot + 1.0)
        )
        if verbosity >= 1:
            print ('cluster: setting thresh using MDL: mdlFactor = %s and'
                   ' numParamsPerLeaf = %s and count = %s' %
                   (self.mdlFactor, numParamsPerLeaf, countRoot))
        return SimpleGrower(thresh, self.minCount, self.maxCount)

@codeDeps(SimpleGrower, SplitInfo, d.DecisionTreeLeaf, d.DecisionTreeNode,
    d.sumValuedRats, maxSplit, partitionLabels, timed
)
class DecisionTreeClusterer(object):
    def __init__(self, accSummer, leafEstimator, grower, verbosity):
        self.accSummer = accSummer
        self.leafEstimator = leafEstimator
        self.grower = grower
        self.verbosity = verbosity

    def getPossSplitIter(self, state, questionGroups):
        """Returns an iterator with one SplitInfo for each allowed question.

        A clustering state is a proto-leaf together with info about its
        position in the tree and enough info about the initial parts of the
        tree to allow clustering of the sub-tree with the proto-leaf as root.
        (This initial tree info consists of the labels remaining and the
        non-trivial question groups remaining).

        For a given state and list of questionGroups, this function returns an
        iterator over splits, one for each allowed question.
        """
        labels, questionGroupsRemaining, isYesList, protoNoSplit = state

        for (
            fullQuestion, accYes, accNo
        ) in self.accSummer.sumAccsForQuestions(labels, questionGroups):
            protoYes = self.leafEstimator.estOrNone(accYes)
            protoNo = self.leafEstimator.estOrNone(accNo)
            splitInfo = SplitInfo(protoNoSplit, fullQuestion,
                                  protoYes, protoNo)
            if self.grower.allowSplit(splitInfo):
                yield splitInfo

    def getPossSplitsWithPrunedQuestionGroups(self, state, questionGroups):
        """Returns a list of possible splits (and an updated questionGroups).

        This method is like getPossSplitIter but returns a list rather than an
        iterator, and returns an updated questionGroups with certain questions
        that can never be selected in future (that is, lower in the tree)
        removed.
        """
        labels, questionGroupsRemaining, isYesList, protoNoSplit = state

        # this method makes assumptions about how allowSplit uses minCount
        assert isinstance(self.grower, SimpleGrower)
        minCount = self.grower.minCount

        questionGroupsOut = []
        splitInfos = []
        for (
            labelValuer, accsForQuestions
        ) in self.accSummer.sumAccsForQuestionGroups(labels, questionGroups):
            questionsOut = []
            for question, accYes, accNo in accsForQuestions:
                if accYes.count() >= minCount and accNo.count() >= minCount:
                    questionsOut.append(question)

                    protoYes = self.leafEstimator.estOrNone(accYes)
                    protoNo = self.leafEstimator.estOrNone(accNo)
                    fullQuestion = labelValuer, question
                    splitInfo = SplitInfo(protoNoSplit, fullQuestion,
                                          protoYes, protoNo)
                    if self.grower.allowSplit(splitInfo):
                        splitInfos.append(splitInfo)
            if questionsOut:
                questionGroupsOut.append((labelValuer, questionsOut))

        return splitInfos, questionGroupsOut

    def getNextStates(self, state, splitInfo):
        labels, questionGroups, isYesList, protoNoSplit = state

        if self.verbosity >= 2:
            indent = '    '+''.join([ ('|  ' if isYes else '   ')
                                      for isYes in isYesList ])
        if self.grower.useSplit(splitInfo):
            labelValuer, question = splitInfo.fullQuestion
            if self.verbosity >= 2:
                print ('cluster:%squestion ( %s %s ) ( delta = %s )' %
                       (indent, labelValuer.shortRepr(), question.shortRepr(),
                        splitInfo.delta()))
            labelsYes, labelsNo = partitionLabels(labels,
                                                  splitInfo.fullQuestion)
            questionGroupsYes = questionGroups
            questionGroupsNo = questionGroups

            return [
                (labelsYes, questionGroupsYes, isYesList + (True,),
                 splitInfo.protoYes),
                (labelsNo, questionGroupsNo, isYesList + (False,),
                 splitInfo.protoNo),
            ]
        else:
            if self.verbosity >= 2:
                print 'cluster:'+indent+'leaf'
            return []

    def maxSplitAndNextStates(self, state, *splitInfos):
        labels, questionGroups, isYesList, protoNoSplit = state

        splitInfo = maxSplit(protoNoSplit, splitInfos)
        nextStates = self.getNextStates(state, splitInfo)
        return splitInfo, nextStates

    def computeBestSplitAndNextStates(self, state):
        labels, questionGroups, isYesList, protoNoSplit = state

        splitInfos, questionGroupsOut = (
            self.getPossSplitsWithPrunedQuestionGroups(state, questionGroups)
        )
        splitInfo = maxSplit(protoNoSplit, splitInfos)
        stateNew = labels, questionGroupsOut, isYesList, protoNoSplit
        nextStates = self.getNextStates(stateNew, splitInfo)
        return splitInfo, nextStates

    def printNodeInfo(self, state):
        labels, questionGroups, isYesList, protoNoSplit = state

        indent = '    '+''.join([ ('|  ' if isYes else '   ')
                                  for isYes in isYesList[:-1] ])
        if not isYesList:
            extra = ''
        elif isYesList[-1]:
            extra = '|->'
        else:
            extra = '\->'
        print ('cluster:%s%snode ( count = %s ,'
               ' remaining labels/QGs/Qs = %s/%s/%s )' %
               (indent, extra, protoNoSplit.count,
                len(labels), len(questionGroups),
                sum([ len(questions)
                      for _, questions in questionGroups ])))

    def subTreeSplitInfoIter(self, stateInit):
        agenda = [stateInit]
        while agenda:
            state = agenda.pop()
            labels, questionGroups, isYesList, protoNoSplit = state
            if self.verbosity >= 2:
                self.printNodeInfo(state)
            if self.verbosity >= 3:
                indent = '    '+''.join([ ('|  ' if isYes else '   ')
                                          for isYes in isYesList ])
                computeBestSplit = timed(
                    self.computeBestSplitAndNextStates,
                    msg = 'cluster:%schoose and perform split took' % indent
                )
            else:
                computeBestSplit = self.computeBestSplitAndNextStates
            splitInfo, nextStates = computeBestSplit(state)
            agenda.extend(reversed(nextStates))
            yield isYesList, splitInfo

    def subTreeSplitInfoIterInGreedyOrder(self, stateInit):
        agenda = []

        def agendaPush(state):
            labels, questionGroups, isYesList, protoNoSplit = state
            splitInfos, questionGroupsOut = (
                self.getPossSplitsWithPrunedQuestionGroups(state,
                                                           questionGroups)
            )
            splitInfo = maxSplit(protoNoSplit, splitInfos)
            stateNew = labels, questionGroupsOut, isYesList, protoNoSplit
            if self.grower.useSplit(splitInfo):
                heapq.heappush(
                    agenda,
                    (-splitInfo.delta(), splitInfo, stateNew)
                )

        agendaPush(stateInit)
        while agenda:
            value, splitInfo, state = heapq.heappop(agenda)
            labels, questionGroups, isYesList, protoNoSplit = state
            if self.verbosity >= 2:
                self.printNodeInfo(state)
            nextStates = self.getNextStates(state, splitInfo)
            for nextState in nextStates:
                agendaPush(nextState)
            yield isYesList, splitInfo

    def constructTree(self, splitInfoDict):
        def construct(isYesList):
            splitInfo = splitInfoDict[isYesList]
            if self.grower.useSplit(splitInfo):
                distYes, auxValuedRatYes = construct(isYesList + (True,))
                distNo, auxValuedRatNo = construct(isYesList + (False,))
                auxValuedRat = d.sumValuedRats([auxValuedRatYes,
                                                auxValuedRatNo])
                distNew = d.DecisionTreeNode(splitInfo.fullQuestion,
                                             distYes, distNo)
                return distNew, auxValuedRat
            else:
                protoNoSplit = splitInfo.protoNoSplit
                auxValuedRat = protoNoSplit.aux, protoNoSplit.auxRat
                return d.DecisionTreeLeaf(protoNoSplit.dist), auxValuedRat

        return construct(())

@codeDeps(d.getDefaultEstimateTotAuxNoRevert)
class ClusteringSpec(object):
    def __init__(self, growerSpec, questionGroups,
                 estimateTotAux = d.getDefaultEstimateTotAuxNoRevert(),
                 verbosity = 2):
        self.growerSpec = growerSpec
        self.questionGroups = questionGroups
        self.estimateTotAux = estimateTotAux
        self.verbosity = verbosity

@codeDeps(AccSummer, DecisionTreeClusterer, LeafEstimator, d.Rat,
    removeTrivialQuestions
)
def decisionTreeCluster(clusteringSpec, labels, accForLabel, createAcc):
    verbosity = clusteringSpec.verbosity
    accSummer = AccSummer(accForLabel, createAcc)
    leafEstimator = LeafEstimator(clusteringSpec.estimateTotAux)
    def getProtoRoot():
        return leafEstimator.est(accSummer.sumAccs(labels))
    if verbosity >= 3:
        getProtoRoot = timed(getProtoRoot)
    protoRoot = getProtoRoot()
    grower = clusteringSpec.growerSpec(protoRoot.dist, protoRoot.count,
                                       verbosity = verbosity)
    clusterer = DecisionTreeClusterer(accSummer, leafEstimator, grower,
                                      verbosity = verbosity)
    if verbosity >= 1:
        print ('cluster: decision tree clustering with thresh = %s and'
               ' minCount = %s and maxCount = %s' %
               (grower.thresh, grower.minCount, grower.maxCount))

    questionGroups = removeTrivialQuestions(labels,
                                            clusteringSpec.questionGroups)
    splitInfoDict = dict(
        clusterer.subTreeSplitInfoIter((labels, questionGroups, (), protoRoot))
    )
    dist, (aux, auxRat) = clusterer.constructTree(splitInfoDict)

    if verbosity >= 1:
        countRoot = protoRoot.count
        print 'cluster: %s leaves' % dist.countLeaves()
        print ('cluster: aux root = %s (%s) -> aux tree = %s (%s) (%s count)' %
               (protoRoot.aux / countRoot, d.Rat.toString(protoRoot.auxRat),
                aux / countRoot, d.Rat.toString(auxRat),
                countRoot))
    return dist

@codeDeps(d.addAcc, d.getDefaultCreateAcc, partitionLabels)
def getDeltaIter(labelsRoot, accForLabel, distRoot, splitIter,
                 createAcc = d.getDefaultCreateAcc()):
    def getLogProb(dist, labels):
        acc = createAcc(dist)
        for label in labels:
            d.addAcc(acc, accForLabel(label))
        return acc.logLike()

    logProbDict = dict()
    logProbDict[()] = getLogProb(distRoot, labelsRoot)
    labelsDict = dict()
    labelsDict[()] = labelsRoot

    for isYesList, fullQuestion, distYes, distNo in splitIter:
        logProb = logProbDict[isYesList]
        labels = labelsDict[isYesList]

        labelsYes, labelsNo = partitionLabels(labels, fullQuestion)
        logProbYes = getLogProb(distYes, labelsYes)
        logProbNo = getLogProb(distNo, labelsNo)

        logProbDict[isYesList + (True,)] = logProbYes
        logProbDict[isYesList + (False,)] = logProbNo
        labelsDict[isYesList + (True,)] = labelsYes
        labelsDict[isYesList + (False,)] = labelsNo

        delta = logProbYes + logProbNo - logProb
        yield delta

@codeDeps(AccSummer, DecisionTreeClusterer, LeafEstimator, getDeltaIter,
    removeTrivialQuestions
)
def decisionTreeClusterInGreedyOrderWithTest(clusteringSpec,
                                             labels, labelsTest,
                                             accForLabel, accForLabelTest,
                                             createAcc):
    verbosity = clusteringSpec.verbosity
    accSummer = AccSummer(accForLabel, createAcc)
    leafEstimator = LeafEstimator(clusteringSpec.estimateTotAux)
    protoRoot = leafEstimator.est(accSummer.sumAccs(labels))
    grower = clusteringSpec.growerSpec(protoRoot.dist, protoRoot.count,
                                       verbosity = verbosity)
    clusterer = DecisionTreeClusterer(accSummer, leafEstimator, grower,
                                      verbosity = verbosity)
    if verbosity >= 1:
        print ('cluster: decision tree clustering with thresh = %s and'
               ' minCount = %s and maxCount = %s' %
               (grower.thresh, grower.minCount, grower.maxCount))

    questionGroups = removeTrivialQuestions(labels,
                                            clusteringSpec.questionGroups)

    # (have to be a bit careful about iterators getting used up; not ideal)
    splitInfoIter = clusterer.subTreeSplitInfoIterInGreedyOrder(
        (labels, questionGroups, (), protoRoot)
    )
    splitInfoIter, splitInfoIter2 = itertools.tee(splitInfoIter, 2)
    splitIter = ( (isYesList, splitInfo.fullQuestion,
                   splitInfo.protoYes.dist, splitInfo.protoNo.dist)
                  for isYesList, splitInfo in splitInfoIter2 )
    deltaIterTrain = ( splitInfo.delta()
                       for isYesList, splitInfo in splitInfoIter )
    deltaIterTest = getDeltaIter(labelsTest, accForLabelTest, protoRoot.dist,
                                 splitIter)
    return itertools.izip(deltaIterTrain, deltaIterTest)
