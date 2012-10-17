"""Example experiments."""

# Copyright 2011, 2012 Matt Shannon

# This file is part of armspeech.
# See `License` for details of license and warranty.


from __future__ import division

import armspeech.modelling.alignment as align
from armspeech.modelling.alignment import StandardizeAlignment
from armspeech.modelling import nodetree
import armspeech.modelling.dist as d
import armspeech.modelling.train as trn
from armspeech.modelling import summarizer
import armspeech.modelling.transform as xf
from armspeech.modelling import cluster
from armspeech.modelling import wnet
from armspeech.speech.features import stdCepDist, stdCepDistIncZero
from armspeech.speech import draw
from armspeech.util.util import identityFn, ConstantFn
from armspeech.util.util import getElem, ElemGetter, AttrGetter
from armspeech.util import persist
from armspeech.util.timing import timed, printTime
from armspeech.modelling.bisque import corpus as corpus_bisque
from armspeech.modelling.bisque import train as train_bisque
from armspeech.bisque.distribute import liftLocal, lit, lift
from codedep import codeDeps

import phoneset_cmu
import labels_hts_demo
import questions_hts_demo
import mgc_lf0_bap
import corpus_arctic

import os
import math
import numpy as np
import armspeech.numpy_settings

@codeDeps(d.reportFloored, getElem, nodetree.findTaggedNodes)
def reportFlooredPerStream(dist):
    def isStreamRoot(tag):
        return getElem(tag, 0, 2) == 'stream'
    for streamRoot in nodetree.findTaggedNodes(dist, isStreamRoot):
        streamName = streamRoot.tag[1]
        d.reportFloored(streamRoot, rootTag = streamName)

@codeDeps(d.Rat)
def reportTrainAux((trainAux, trainAuxRat), trainFrames):
    print 'training aux = %s (%s) (%s frames)' % (trainAux / trainFrames, d.Rat.toString(trainAuxRat), trainFrames)

@codeDeps()
def evaluateLogProb(dist, corpus):
    trainLogProb = corpus.logProb(dist, corpus.trainUttIds)
    trainFrames = corpus.frames(corpus.trainUttIds)
    print 'train set log prob = %s (%s frames)' % (trainLogProb / trainFrames, trainFrames)
    testLogProb = corpus.logProb(dist, corpus.testUttIds)
    testFrames = corpus.frames(corpus.testUttIds)
    print 'test set log prob = %s (%s frames)' % (testLogProb / testFrames, testFrames)
    print
    return [('train log prob', (trainLogProb, trainFrames)),
            ('test log prob', (testLogProb, testFrames))]

@codeDeps(d.SynthMethod, stdCepDist)
def evaluateMgcArOutError(dist, corpus, vecError = stdCepDist, desc = 'MARCD'):
    def frameToVec(frame):
        mgcFrame, lf0Frame, bapFrame = frame
        return mgcFrame
    def distError(dist, input, actualFrame):
        synthFrame = dist.synth(input, d.SynthMethod.Meanish, actualFrame)
        return vecError(frameToVec(synthFrame), frameToVec(actualFrame))
    def computeValue(inputUtt, outputUtt):
        return dist.sum(inputUtt, outputUtt, distError)
    trainError = corpus.sum(corpus.trainUttIds, computeValue)
    trainFrames = corpus.frames(corpus.trainUttIds)
    print 'train set %s = %s (%s frames)' % (desc, trainError / trainFrames, trainFrames)
    testError = corpus.sum(corpus.testUttIds, computeValue)
    testFrames = corpus.frames(corpus.testUttIds)
    print 'test set %s = %s (%s frames)' % (desc, testError / testFrames, testFrames)
    print
    return [('train %s' % desc, (trainError, trainFrames)),
            ('test %s' % desc, (testError, testFrames))]

@codeDeps(stdCepDist)
def evaluateMgcOutError(dist, corpus, vecError = stdCepDist, desc = 'MCD'):
    def frameToVec(frame):
        mgcFrame, lf0Frame, bapFrame = frame
        return mgcFrame
    trainError = corpus.outError(dist, corpus.trainUttIds, vecError, frameToVec)
    trainFrames = corpus.frames(corpus.trainUttIds)
    print 'train set %s = %s (%s frames)' % (desc, trainError / trainFrames, trainFrames)
    testError = corpus.outError(dist, corpus.testUttIds, vecError, frameToVec)
    testFrames = corpus.frames(corpus.testUttIds)
    print 'test set %s = %s (%s frames)' % (desc, testError / testFrames, testFrames)
    print
    return [('train %s' % desc, (trainError, trainFrames)),
            ('test %s' % desc, (testError, testFrames))]

@codeDeps(d.SynthMethod)
def evaluateSynthesize(dist, corpus, synthOutDir, exptTag, afterSynth = None):
    corpus.synthComplete(dist, corpus.synthUttIds, d.SynthMethod.Sample, synthOutDir, exptTag+'.sample', afterSynth = afterSynth)
    corpus.synthComplete(dist, corpus.synthUttIds, d.SynthMethod.Meanish, synthOutDir, exptTag+'.meanish', afterSynth = afterSynth)

@codeDeps(draw.drawLabelledSeq, draw.partitionSeq)
def getDrawMgc(corpus, mgcIndices, figOutDir, ylims = None, includeGivenLabels = True, extraLabelSeqs = []):
    streamIndex = 0
    def drawMgc(synthOutput, uttId, exptTag):
        (uttId, alignment), trueOutput = corpus.data(uttId)

        alignmentToDraw = [ (start * corpus.framePeriod, end * corpus.framePeriod, label.phone) for start, end, label, subAlignment in alignment ]
        partitionedLabelSeqs = (draw.partitionSeq(alignmentToDraw, 2) if includeGivenLabels else []) + [ labelSeqSub for labelSeq in extraLabelSeqs for labelSeqSub in draw.partitionSeq(labelSeq, 2) ]

        trueSeqTime = (np.array(range(len(trueOutput))) + 0.5) * corpus.framePeriod
        synthSeqTime = (np.array(range(len(synthOutput))) + 0.5) * corpus.framePeriod

        for mgcIndex in mgcIndices:
            trueSeq = [ frame[streamIndex][mgcIndex] for frame in trueOutput ]
            synthSeq = [ frame[streamIndex][mgcIndex] for frame in synthOutput ]

            outPdf = os.path.join(figOutDir, uttId+'-mgc'+str(mgcIndex)+'-'+exptTag+'.pdf')
            draw.drawLabelledSeq([(trueSeqTime, trueSeq), (synthSeqTime, synthSeq)], partitionedLabelSeqs, outPdf = outPdf, figSizeRate = 10.0, ylims = ylims, colors = ['red', 'purple'])
    return drawMgc

@codeDeps(evaluateLogProb, evaluateMgcArOutError, evaluateMgcOutError,
    evaluateSynthesize, getDrawMgc, persist.savePickle, reportFlooredPerStream,
    stdCepDistIncZero
)
def evaluateVarious(dist, bmi, corpus, synthOutDir, figOutDir, exptTag, vecError = stdCepDistIncZero):
    # FIXME : vecError default should probably be changed to stdCepDist eventually
    reportFlooredPerStream(dist)
    # (FIXME : perhaps this shouldn't really go in synthOutDir)
    persist.savePickle(os.path.join(synthOutDir, 'dist-%s.pkl' % exptTag),
                       dist)
    logProbResults = evaluateLogProb(dist, corpus)
    marcdResults = evaluateMgcOutError(dist, corpus, vecError = vecError)
    mcdResults = evaluateMgcArOutError(dist, corpus, vecError = vecError)
    evaluateSynthesize(dist, corpus, synthOutDir, exptTag, afterSynth = getDrawMgc(corpus, bmi.mgcSummarizer.outIndices, figOutDir))
    return logProbResults + marcdResults + mcdResults

@codeDeps(d.defaultEstimatePartial, nodetree.getDagMap,
    trn.mixupLinearGaussianEstimatePartial
)
def getMixupEstimate():
    return nodetree.getDagMap([trn.mixupLinearGaussianEstimatePartial,
                               d.defaultEstimatePartial])

@codeDeps(d.getDefaultCreateAcc, getMixupEstimate, trn.trainEM)
def mixup(dist, accumulate):
    print
    print 'MIXING UP'
    acc = d.getDefaultCreateAcc()(dist)
    accumulate(acc)
    logLikeInit = acc.logLike()
    framesInit = acc.count()
    print 'initial training log likelihood = %s (%s frames)' % (logLikeInit / framesInit, framesInit)
    dist = getMixupEstimate()(acc)
    dist = trn.trainEM(dist, accumulate, deltaThresh = 1e-4, minIterations = 4, maxIterations = 8, verbosity = 2)
    return dist

@codeDeps(getMixupEstimate, liftLocal, lit, train_bisque.accumulateJobSet,
    train_bisque.estimateJobSet, train_bisque.trainEMJobSet
)
def mixupJobSet(distArt, corpusArt, uttIdChunkArts):
    accArts = train_bisque.accumulateJobSet(distArt, corpusArt, uttIdChunkArts)
    distArt = train_bisque.estimateJobSet(
        distArt,
        accArts,
        estimateArt = liftLocal(getMixupEstimate)(),
        verbosityArt = lit(2)
    )
    distArt = train_bisque.trainEMJobSet(distArt, corpusArt, uttIdChunkArts,
                                         numIterationsLit = lit(8),
                                         verbosityArt = lit(2))
    return distArt

@codeDeps(d.DebugDist, d.LinearGaussian, d.MappedInputDist, d.StudentDist,
    d.TransformedOutputDist, nodetree.defaultMapPartial, nodetree.getDagMap,
    xf.ConstantTransform, xf.DotProductTransform, xf.ShiftOutputTransform
)
def convertToStudentResiduals(dist, studentTag = None, debugTag = None, subtractMeanTag = None):
    def studentResidualsMapPartial(dist, mapChild):
        if isinstance(dist, d.LinearGaussian):
            subDist = d.StudentDist(df = 10000.0, precision = 1.0 / dist.variance).withTag(studentTag)
            if debugTag is not None:
                subDist = d.DebugDist(None, subDist).withTag(debugTag)
            subtractMeanTransform = xf.ShiftOutputTransform(xf.DotProductTransform(-dist.coeff)).withTag(subtractMeanTag)
            distNew = d.TransformedOutputDist(subtractMeanTransform,
                d.MappedInputDist(xf.ConstantTransform(np.array([])),
                    subDist
                )
            )
            return distNew
    studentResidualsMap = nodetree.getDagMap([studentResidualsMapPartial, nodetree.defaultMapPartial])

    return studentResidualsMap(dist)

@codeDeps(d.DebugDist, d.LinearGaussian, d.MappedInputDist,
    d.TransformedOutputDist, nodetree.defaultMapPartial, nodetree.getDagMap,
    xf.ConstantTransform, xf.DotProductTransform, xf.IdentityTransform,
    xf.ShiftOutputTransform, xf.SimpleOutputTransform, xf.SumTransform1D,
    xf.TanhTransform1D
)
def convertToTransformedGaussianResiduals(dist, residualTransformTag = None, debugTag = None, subtractMeanTag = None):
    def transformedGaussianResidualsMapPartial(dist, mapChild):
        if isinstance(dist, d.LinearGaussian):
            residualTransform = xf.SimpleOutputTransform(xf.SumTransform1D([
                xf.IdentityTransform()
            ,   xf.TanhTransform1D(np.array([0.0, 0.5, -1.0]))
            ,   xf.TanhTransform1D(np.array([0.0, 0.5, 0.0]))
            ,   xf.TanhTransform1D(np.array([0.0, 0.5, 1.0]))
            ]), checkDerivPositive1D = True).withTag(residualTransformTag)

            subDist = d.TransformedOutputDist(residualTransform,
                d.LinearGaussian(np.array([]), dist.variance, varianceFloor = 0.0)
            )
            if debugTag is not None:
                subDist = d.DebugDist(None, subDist).withTag(debugTag)
            subtractMeanTransform = xf.ShiftOutputTransform(xf.DotProductTransform(-dist.coeff)).withTag(subtractMeanTag)
            distNew = d.TransformedOutputDist(subtractMeanTransform,
                d.MappedInputDist(xf.ConstantTransform(np.array([])),
                    subDist
                )
            )
            return distNew
    transformedGaussianResidualsMap = nodetree.getDagMap([transformedGaussianResidualsMapPartial, nodetree.defaultMapPartial])

    return transformedGaussianResidualsMap(dist)

@codeDeps(d.LinearGaussian, d.MappedInputDist, xf.AddBias)
def createLinearGaussianVectorDist(indexSpecSummarizer):
    """Creates a linear-Gaussian vector dist.

    Expects input acInput.
    """
    def distFor(outIndex):
        inputLength = indexSpecSummarizer.vectorLength(outIndex) + 1
        return d.MappedInputDist(xf.AddBias(),
            d.LinearGaussian(
                coeff = np.zeros((inputLength,)),
                variance = 1.0,
                varianceFloor = 0.0
            )
        )

    return indexSpecSummarizer.createDist(False, distFor)

@codeDeps(d.LinearGaussian, d.MappedInputDist, xf.AddBias)
def createLinearGaussianWithTimingVectorDist(indexSpecSummarizer):
    """Creates a linear-Gaussian vector dist where input includes timing info.

    Expects input (timingInfo, acInput) where timingInfo is
    (framesBefore, framesAfter).
    """
    extraLength = 2
    def distFor(outIndex):
        inputLength = (indexSpecSummarizer.vectorLength(outIndex) +
                       extraLength + 1)
        # from (timingInfo, acInputSingle) to (timingInfo + acInputSingle)
        #   where acInputSingle is a vector which is the acoustic context for a
        #   single outIndex
        return d.MappedInputDist(np.concatenate,
            d.MappedInputDist(xf.AddBias(),
                d.LinearGaussian(
                    coeff = np.zeros((inputLength,)),
                    variance = 1.0,
                    varianceFloor = 0.0
                )
            )
        )

    return indexSpecSummarizer.createDist(True, distFor)

@codeDeps(d.BinaryLogisticClassifier, d.FixedValueDist,
    d.IdentifiableMixtureDist, d.LinearGaussian, d.MappedInputDist, xf.AddBias,
    xf.Msd01ToVector
)
def createBlcBasedLf0Dist(lf0Depth):
    return d.MappedInputDist(xf.Msd01ToVector(),
        d.MappedInputDist(xf.AddBias(),
            d.IdentifiableMixtureDist(
                d.BinaryLogisticClassifier(
                    coeff = np.zeros((2 * lf0Depth + 1,)),
                    coeffFloor = np.ones((2 * lf0Depth + 1,)) * 5.0
                ),
                [
                    d.FixedValueDist(None),
                    d.LinearGaussian(
                        coeff = np.zeros((2 * lf0Depth + 1,)),
                        variance = 1.0,
                        varianceFloor = 0.0
                    )
                ]
            )
        )
    )

@codeDeps()
def tupleMap1(((a, b), c)):
    return a, (b, c)

@codeDeps()
def tupleMap1Phone(((label, subLabel), acInput)):
    return subLabel, (label.phone, acInput)

@codeDeps(d.MappedInputDist, d.createDiscreteDist, d.isolateDist, getElem,
    nodetree.defaultMapPartial, nodetree.findTaggedNode, nodetree.getDagMap,
    tupleMap1Phone
)
def globalToMonophoneMap(dist, bmi):
    """Converts a global dist to a monophone dist.

    Expects stream tag to be ('stream', streamName) with input
    ((label, subLabel), acInput).
    Expects acoustic vector tag to be 'acVec' with input acInput.

    The returned dist maintains these properties.
    """
    def globalToMonophoneMapPartial(dist, mapChild):
        if getElem(dist.tag, 0, 2) == 'stream':
            acVecDist = nodetree.findTaggedNode(dist,
                                                lambda tag: tag == 'acVec')
            return d.MappedInputDist(tupleMap1Phone,
                d.createDiscreteDist(bmi.subLabels, lambda subLabel:
                    d.createDiscreteDist(bmi.phoneset.phoneList, lambda phone:
                        d.isolateDist(acVecDist)
                    )
                )
            ).withTag(dist.tag)

    return nodetree.getDagMap([globalToMonophoneMapPartial,
                               nodetree.defaultMapPartial])(dist)

@codeDeps(d.AutoGrowingDiscreteAcc, d.MappedInputAcc, d.createDiscreteAcc,
    d.defaultCreateAccPartial, d.getDefaultCreateAcc, getElem,
    nodetree.findTaggedNode, nodetree.getDagMap, tupleMap1
)
def globalToFullCtxCreateAcc(dist, bmi):
    """Converts a global dist to a full context acc.

    Expects stream tag to be ('stream', streamName) with input
    ((label, subLabel), acInput).
    Expects acoustic vector tag to be 'acVec' with input acInput.

    The returned dist maintains these properties.
    """
    def globalToFullCtxCreateAccPartial(dist, createAccChild):
        if getElem(dist.tag, 0, 2) == 'stream':
            acVecDist = nodetree.findTaggedNode(dist,
                                                lambda tag: tag == 'acVec')
            def createAcc():
                return d.getDefaultCreateAcc()(acVecDist)
            return d.MappedInputAcc(tupleMap1,
                d.createDiscreteAcc(bmi.subLabels, lambda subLabel:
                    d.AutoGrowingDiscreteAcc(createAcc)
                )
            ).withTag(dist.tag)

    return nodetree.getDagMap([globalToFullCtxCreateAccPartial,
                               d.defaultCreateAccPartial])(dist)

@codeDeps(ElemGetter, align.AlignmentToPhoneticSeq, align.StandardizeAlignment,
    createLinearGaussianVectorDist, d.AutoregressiveSequenceDist,
    d.MappedInputDist, d.OracleDist, mgc_lf0_bap.computeFirstFrameAverage
)
def getInitDist1(bmi, corpus, alignmentSubLabels = 'sameAsBmi'):
    """Produces an initial dist.

    Has stream tag ('stream', streamName) with input (phInput, acInput).
    Has acoustic vector tag 'acVec' with input acInput.
    """
    initialFrame = mgc_lf0_bap.computeFirstFrameAverage(corpus, bmi.mgcOrder,
                                                        bmi.bapOrder)
    if alignmentSubLabels == 'sameAsBmi':
        alignmentSubLabels = bmi.subLabels
    alignmentToPhoneticSeq = align.AlignmentToPhoneticSeq(
        mapAlignment = align.StandardizeAlignment(
            corpus.subLabels, alignmentSubLabels
        )
    )
    createLeafDists = [
        lambda: createLinearGaussianVectorDist(bmi.mgcSummarizer),
        d.OracleDist,
        d.OracleDist,
    ]
    getAcInput = ElemGetter(1, 2)
    dist = d.AutoregressiveSequenceDist(
        bmi.maxDepth,
        alignmentToPhoneticSeq,
        [ initialFrame for i in range(bmi.maxDepth) ],
        bmi.frameSummarizer.createDist(True, lambda streamIndex:
            d.MappedInputDist(getAcInput,
                createLeafDists[streamIndex]().withTag('acVec')
            ).withTag(('stream', corpus.streams[streamIndex].name))
        )
    )
    return dist

@codeDeps(ElemGetter, align.AlignmentToPhoneticSeqWithTiming,
    align.StandardizeAlignment, createLinearGaussianWithTimingVectorDist,
    d.AutoregressiveSequenceDist, d.MappedInputDist, d.OracleDist,
    mgc_lf0_bap.computeFirstFrameAverage, tupleMap1
)
def getInitDist2(bmi, corpus, alignmentSubLabels = 'sameAsBmi'):
    """Produces an initial dist which uses timings.

    Has stream tag ('stream', streamName) with input
    (phInput, (timingInfo, acInput)) where timingInfo is
    (framesBefore, framesAfter).
    Has acoustic vector tag 'acVec' with input (timingInfo, acInput).
    """
    initialFrame = mgc_lf0_bap.computeFirstFrameAverage(corpus, bmi.mgcOrder,
                                                        bmi.bapOrder)
    if alignmentSubLabels == 'sameAsBmi':
        alignmentSubLabels = bmi.subLabels
    alignmentToPhoneticSeq = align.AlignmentToPhoneticSeqWithTiming(
        mapAlignment = align.StandardizeAlignment(
            corpus.subLabels, alignmentSubLabels
        )
    )
    createLeafDists = [
        lambda: createLinearGaussianWithTimingVectorDist(bmi.mgcSummarizer),
        d.OracleDist,
        d.OracleDist,
    ]
    dropPhInput = ElemGetter(1, 2)
    dist = d.AutoregressiveSequenceDist(
        bmi.maxDepth,
        alignmentToPhoneticSeq,
        [ initialFrame for i in range(bmi.maxDepth) ],
        bmi.frameSummarizer.createDist(True, lambda streamIndex:
            # from ((phInput, timingInfo), acInput)
            #   to (phInput, (timingInfo, acInput))
            d.MappedInputDist(tupleMap1,
                d.MappedInputDist(dropPhInput,
                    createLeafDists[streamIndex]().withTag('acVec')
                ).withTag(('stream', corpus.streams[streamIndex].name))
            )
        )
    )
    return dist

@codeDeps(corpus_arctic.getCorpusSynthFewer, corpus_arctic.getTrainUttIds,
    labels_hts_demo.getParseLabel
)
def getCorpus():
    return corpus_arctic.getCorpusSynthFewer(
        trainUttIds = corpus_arctic.getTrainUttIds(),
        parseLabel = labels_hts_demo.getParseLabel(),
        subLabels = None,
        mgcOrder = 40,
        dataDir = '## TBA: fill-in data dir here ##',
        labDir = '## TBA: fill-in lab dir for phone-level alignments here ##',
        scriptsDir = 'scripts',
    )

@codeDeps(corpus_arctic.getCorpusSynthFewer, corpus_arctic.getTrainUttIds,
    labels_hts_demo.getParseLabel
)
def getCorpusWithSubLabels():
    return corpus_arctic.getCorpusSynthFewer(
        trainUttIds = corpus_arctic.getTrainUttIds(),
        parseLabel = labels_hts_demo.getParseLabel(),
        subLabels = list(range(5)),
        mgcOrder = 40,
        dataDir = '## TBA: fill-in data dir here ##',
        labDir = '## TBA: fill-in lab dir for state-level alignments here ##',
        scriptsDir = 'scripts',
    )

@codeDeps(mgc_lf0_bap.BasicArModelInfo, phoneset_cmu.CmuPhoneset)
def getBmiForCorpus(corpus, subLabels = 'sameAsCorpus'):
    if subLabels == 'sameAsCorpus':
        subLabels = corpus.subLabels
    return mgc_lf0_bap.BasicArModelInfo(
        phoneset = phoneset_cmu.CmuPhoneset(),
        subLabels = subLabels,
        mgcOrder = corpus.mgcOrder,
        bapOrder = corpus.bapOrder,
        mgcDepth = 3,
        lf0Depth = 2,
        bapDepth = 3,
        mgcIndices = [0],
        bapIndices = [],
    )

@codeDeps()
def minusPrevAc((ph, ac)):
    return -ac[-1]

# (FIXME : this somewhat unnecessarily uses lots of memory)
@codeDeps(StandardizeAlignment, align.AlignmentToPhoneticSeq,
    d.AutoregressiveSequenceDist, d.DebugDist, d.MappedOutputDist, d.OracleDist,
    d.getDefaultCreateAcc, getBmiForCorpus, getCorpusWithSubLabels,
    mgc_lf0_bap.computeFirstFrameAverage, minusPrevAc, nodetree.findTaggedNode,
    printTime, questions_hts_demo.getTriphoneQuestionGroups, timed,
    xf.ShiftOutputTransform
)
def doDumpCorpus(outDir):
    print
    print 'DUMPING CORPUS'
    printTime('started dumpCorpus')

    corpus = getCorpusWithSubLabels()
    bmi = getBmiForCorpus(corpus)

    print 'numSubLabels =', len(bmi.subLabels)

    questionGroups = questions_hts_demo.getTriphoneQuestionGroups(bmi.phoneset)

    def getQuestionAnswers(label):
        questionAnswers = []
        for labelValuer, questions in questionGroups:
            labelValue = labelValuer(label)
            for question in questions:
                questionAnswers.append(question(labelValue))
        return questionAnswers

    alignmentToPhoneticSeq = align.AlignmentToPhoneticSeq(
        mapAlignment = StandardizeAlignment(corpus.subLabels, bmi.subLabels),
        mapLabel = getQuestionAnswers
    )

    initialFrame = mgc_lf0_bap.computeFirstFrameAverage(corpus, bmi.mgcOrder,
                                                        bmi.bapOrder)

    # FIXME : only works if no cross-stream stuff happening. Make more robust somehow.
    shiftToPrevTransform = xf.ShiftOutputTransform(minusPrevAc)

    dist = d.AutoregressiveSequenceDist(
        bmi.maxDepth,
        alignmentToPhoneticSeq,
        [ initialFrame for i in range(bmi.maxDepth) ],
        bmi.frameSummarizer.createDist(True, lambda streamIndex:
            {
                0:
                    bmi.mgcSummarizer.createDist(True, lambda outIndex:
                        d.MappedOutputDist(shiftToPrevTransform,
                            d.DebugDist(None,
                                d.OracleDist()
                            ).withTag(('debug-mgc', outIndex))
                        )
                    )
            ,   1:
                    d.OracleDist()
            ,   2:
                    d.OracleDist()
            }[streamIndex]
        )
    )

    def accumulate(acc, uttIds):
        for uttId in uttIds:
            input, output = corpus.data(uttId)
            acc.add(input, output)

    trainAcc = d.getDefaultCreateAcc()(dist)
    timed(accumulate)(trainAcc, corpus.trainUttIds)

    testAcc = d.getDefaultCreateAcc()(dist)
    timed(accumulate)(testAcc, corpus.testUttIds)

    for desc, acc in [('train', trainAcc), ('test', testAcc)]:
        for outIndex in bmi.mgcSummarizer.outIndices:
            debugAcc = nodetree.findTaggedNode(acc, lambda tag: tag == ('debug-mgc', outIndex))

            dumpInputFn = os.path.join(outDir, 'corpus-'+desc+'-in.mgc'+str(outIndex)+'.mat')
            with open(dumpInputFn, 'w') as f:
                print 'dump: dumping corpus input to:', dumpInputFn
                for (questionAnswers, subLabel), acInput in debugAcc.memo.inputs:
                    f.write(' '.join(
                        [ ('1' if questionAnswer else '0') for questionAnswer in questionAnswers ] +
                        [ str(subLabel) ]+
                        [ str(x) for x in acInput ]
                    )+'\n')

            dumpOutputFn = os.path.join(outDir, 'corpus-'+desc+'-out.mgc'+str(outIndex)+'.mat')
            with open(dumpOutputFn, 'w') as f:
                print 'dump: dumping corpus output to:', dumpOutputFn
                for acOutput in debugAcc.memo.outputs:
                    f.write(str(acOutput)+'\n')

    printTime('finished dumpCorpus')

@codeDeps(d.FloorSetter, evaluateVarious, getBmiForCorpus,
    getCorpusWithSubLabels, getInitDist1, mixup, printTime,
    trn.expectationMaximization
)
def doGlobalSystem(synthOutDir, figOutDir):
    print
    print 'TRAINING GLOBAL SYSTEM'
    printTime('started global')

    corpus = getCorpusWithSubLabels()
    bmi = getBmiForCorpus(corpus)

    print 'numSubLabels =', len(bmi.subLabels)

    dist = getInitDist1(bmi, corpus)

    # train global dist while setting floors
    dist, _, _, _ = trn.expectationMaximization(
        dist,
        corpus.accumulate,
        afterAcc = d.FloorSetter(lgFloorMult = 1e-3),
        verbosity = 2,
    )
    results = evaluateVarious(dist, bmi, corpus, synthOutDir, figOutDir, exptTag = 'global')

    dist = mixup(dist, corpus.accumulate)
    results = evaluateVarious(dist, bmi, corpus, synthOutDir, figOutDir, exptTag = 'global.2mix')

    dist = mixup(dist, corpus.accumulate)
    results = evaluateVarious(dist, bmi, corpus, synthOutDir, figOutDir, exptTag = 'global.4mix')

    printTime('finished global')

@codeDeps(corpus_bisque.getUttIdChunkArts, d.FloorSetter, evaluateVarious,
    getBmiForCorpus, getCorpusWithSubLabels, getInitDist1, lift, liftLocal, lit,
    mixupJobSet, train_bisque.expectationMaximizationJobSet
)
def doGlobalSystemJobSet(synthOutDirArt, figOutDirArt):
    corpusArt = liftLocal(getCorpusWithSubLabels)()
    bmiArt = liftLocal(getBmiForCorpus)(corpusArt)

    uttIdChunkArts = corpus_bisque.getUttIdChunkArts(corpusArt,
                                                     numChunksLit = lit(2))

    distArt = lift(getInitDist1)(bmiArt, corpusArt)

    # train global dist while setting floors
    distArt = train_bisque.expectationMaximizationJobSet(
        distArt,
        corpusArt,
        uttIdChunkArts,
        afterAccArt = liftLocal(d.FloorSetter)(lgFloorMult = lit(1e-3)),
        verbosityArt = lit(2),
    )
    results1Art = lift(evaluateVarious)(
        distArt, bmiArt, corpusArt, synthOutDirArt, figOutDirArt,
        exptTag = lit('global')
    )

    distArt = mixupJobSet(distArt, corpusArt, uttIdChunkArts)
    results2Art = lift(evaluateVarious)(
        distArt, bmiArt, corpusArt, synthOutDirArt, figOutDirArt,
        exptTag = lit('global.2mix')
    )

    distArt = mixupJobSet(distArt, corpusArt, uttIdChunkArts)
    results4Art = lift(evaluateVarious)(
        distArt, bmiArt, corpusArt, synthOutDirArt, figOutDirArt,
        exptTag = lit('global.4mix')
    )

    return results1Art, results2Art, results4Art

@codeDeps(d.FloorSetter, evaluateVarious, getBmiForCorpus,
    getCorpusWithSubLabels, getInitDist1, globalToMonophoneMap, mixup,
    printTime, trn.expectationMaximization
)
def doMonophoneSystem(synthOutDir, figOutDir):
    print
    print 'TRAINING MONOPHONE SYSTEM'
    printTime('started mono')

    corpus = getCorpusWithSubLabels()
    bmi = getBmiForCorpus(corpus)

    print 'numSubLabels =', len(bmi.subLabels)

    dist = getInitDist1(bmi, corpus)

    # train global dist while setting floors
    dist, _, _, _ = trn.expectationMaximization(
        dist,
        corpus.accumulate,
        afterAcc = d.FloorSetter(lgFloorMult = 1e-3),
        verbosity = 2,
    )

    print 'DEBUG: converting global dist to monophone dist'
    dist = globalToMonophoneMap(dist, bmi)

    dist = trn.expectationMaximization(dist, corpus.accumulate, verbosity = 2)[0]
    results = evaluateVarious(dist, bmi, corpus, synthOutDir, figOutDir, exptTag = 'mono')

    dist = mixup(dist, corpus.accumulate)
    results = evaluateVarious(dist, bmi, corpus, synthOutDir, figOutDir, exptTag = 'mono.2mix')

    dist = mixup(dist, corpus.accumulate)
    results = evaluateVarious(dist, bmi, corpus, synthOutDir, figOutDir, exptTag = 'mono.4mix')

    printTime('finished mono')

@codeDeps(corpus_bisque.getUttIdChunkArts, d.FloorSetter, evaluateVarious,
    getBmiForCorpus, getCorpusWithSubLabels, getInitDist1, globalToMonophoneMap,
    lift, liftLocal, lit, mixupJobSet,
    train_bisque.expectationMaximizationJobSet
)
def doMonophoneSystemJobSet(synthOutDirArt, figOutDirArt):
    corpusArt = liftLocal(getCorpusWithSubLabels)()
    bmiArt = liftLocal(getBmiForCorpus)(corpusArt)

    uttIdChunkArts = corpus_bisque.getUttIdChunkArts(corpusArt,
                                                     numChunksLit = lit(2))

    distArt = lift(getInitDist1)(bmiArt, corpusArt)

    # train global dist while setting floors
    distArt = train_bisque.expectationMaximizationJobSet(
        distArt,
        corpusArt,
        uttIdChunkArts,
        afterAccArt = liftLocal(d.FloorSetter)(lgFloorMult = lit(1e-3)),
        verbosityArt = lit(2),
    )

    distArt = lift(globalToMonophoneMap)(distArt, bmiArt)

    distArt = train_bisque.expectationMaximizationJobSet(
        distArt,
        corpusArt,
        uttIdChunkArts,
        verbosityArt = lit(2),
    )
    results1Art = lift(evaluateVarious)(
        distArt, bmiArt, corpusArt, synthOutDirArt, figOutDirArt,
        exptTag = lit('mono')
    )

    distArt = mixupJobSet(distArt, corpusArt, uttIdChunkArts)
    results2Art = lift(evaluateVarious)(
        distArt, bmiArt, corpusArt, synthOutDirArt, figOutDirArt,
        exptTag = lit('mono.2mix')
    )

    distArt = mixupJobSet(distArt, corpusArt, uttIdChunkArts)
    results4Art = lift(evaluateVarious)(
        distArt, bmiArt, corpusArt, synthOutDirArt, figOutDirArt,
        exptTag = lit('mono.4mix')
    )

    return results1Art, results2Art, results4Art

@codeDeps(d.FloorSetter, evaluateVarious, getBmiForCorpus,
    getCorpusWithSubLabels, getInitDist2, globalToMonophoneMap, printTime,
    trn.expectationMaximization
)
def doTimingInfoSystem(synthOutDir, figOutDir):
    print
    print 'TRAINING MONOPHONE SYSTEM WITH TIMING INFO'
    printTime('started timingInfo')

    corpus = getCorpusWithSubLabels()
    bmi = getBmiForCorpus(corpus)

    print 'numSubLabels =', len(bmi.subLabels)

    dist = getInitDist2(bmi, corpus)

    # train global dist while setting floors
    dist, _, _, _ = trn.expectationMaximization(
        dist,
        corpus.accumulate,
        afterAcc = d.FloorSetter(lgFloorMult = 1e-3),
        verbosity = 2,
    )

    print 'DEBUG: converting global dist to monophone dist'
    dist = globalToMonophoneMap(dist, bmi)

    dist = trn.expectationMaximization(dist, corpus.accumulate, verbosity = 2)[0]
    results = evaluateVarious(dist, bmi, corpus, synthOutDir, figOutDir, exptTag = 'timingInfo')

    printTime('finished timingInfo')

@codeDeps(cluster.decisionTreeCluster, d.AutoGrowingDiscreteAcc, d.FloorSetter,
    d.defaultEstimatePartial, evaluateVarious, getBmiForCorpus,
    getCorpusWithSubLabels, getInitDist1, globalToFullCtxCreateAcc, mixup,
    nodetree.getDagMap, printTime,
    questions_hts_demo.getFullContextQuestionGroups, timed,
    trn.expectationMaximization
)
def doDecisionTreeClusteredSystem(synthOutDir, figOutDir, mdlFactor = 0.3):
    print
    print 'DECISION TREE CLUSTERING'
    printTime('started clustered')

    corpus = getCorpusWithSubLabels()
    bmi = getBmiForCorpus(corpus)

    print 'numSubLabels =', len(bmi.subLabels)

    dist = getInitDist1(bmi, corpus)

    # train global dist while setting floors
    dist, _, _, _ = trn.expectationMaximization(
        dist,
        corpus.accumulate,
        afterAcc = d.FloorSetter(lgFloorMult = 1e-3),
        verbosity = 2,
    )

    print 'DEBUG: converting global dist to full ctx acc'
    acc = globalToFullCtxCreateAcc(dist, bmi)

    print 'DEBUG: accumulating for decision tree clustering'
    timed(corpus.accumulate)(acc)

    questionGroups = questions_hts_demo.getFullContextQuestionGroups(bmi.phoneset)

    def decisionTreeClusterEstimatePartial(acc, estimateChild):
        if isinstance(acc, d.AutoGrowingDiscreteAcc):
            return timed(cluster.decisionTreeCluster)(acc.accDict.keys(), lambda label: acc.accDict[label], acc.createAcc, questionGroups, thresh = None, mdlFactor = mdlFactor, minCount = 10.0, maxCount = None, verbosity = 3)
    decisionTreeClusterEstimate = nodetree.getDagMap([decisionTreeClusterEstimatePartial, d.defaultEstimatePartial])

    dist = decisionTreeClusterEstimate(acc)
    print
    results = evaluateVarious(dist, bmi, corpus, synthOutDir, figOutDir, exptTag = 'clustered')

    dist = mixup(dist, corpus.accumulate)
    results = evaluateVarious(dist, bmi, corpus, synthOutDir, figOutDir, exptTag = 'clustered.2mix')

    dist = mixup(dist, corpus.accumulate)
    results = evaluateVarious(dist, bmi, corpus, synthOutDir, figOutDir, exptTag = 'clustered.4mix')

    printTime('finished clustered')

@codeDeps(AttrGetter, ConstantFn, StandardizeAlignment,
    align.AlignmentToPhoneticSeq, convertToStudentResiduals,
    convertToTransformedGaussianResiduals, d.AutoregressiveSequenceDist,
    d.DebugDist, d.LinearGaussian, d.MappedInputDist, d.OracleDist,
    d.TransformedInputDist, d.TransformedOutputDist, d.createDiscreteDist,
    d.getByTagParamSpec, d.getDefaultParamSpec, draw.drawFor1DInput,
    draw.drawLogPdf, draw.drawWarping, evaluateVarious, getBmiForCorpus,
    getCorpusWithSubLabels, getElem, mgc_lf0_bap.computeFirstFrameAverage,
    nodetree.findTaggedNode, nodetree.findTaggedNodes, printTime, timed,
    trn.trainCG, trn.trainCGandEM, trn.trainEM, tupleMap1, xf.AddBias,
    xf.IdentityTransform, xf.MinusPrev, xf.ShiftOutputTransform,
    xf.SimpleOutputTransform, xf.SumTransform1D, xf.TanhTransform1D,
    xf.VectorizeTransform
)
def doTransformSystem(synthOutDir, figOutDir, globalPhone = True, studentResiduals = True, numTanhTransforms = 3):
    print
    print 'TRAINING TRANSFORM SYSTEM'
    printTime('started xf')

    corpus = getCorpusWithSubLabels()
    bmi = getBmiForCorpus(corpus)

    print 'globalPhone =', globalPhone
    print 'studentResiduals =', studentResiduals
    # mgcDepth affects what pictures we can draw
    print 'mgcDepth =', bmi.mgcDepth
    print 'numTanhTransforms =', numTanhTransforms

    # N.B. would be perverse to have globalPhone == True with numSubLabels != 1, but not disallowed
    phoneList = ['global'] if globalPhone else bmi.phoneset.phoneList

    print 'numSubLabels =', len(bmi.subLabels)

    alignmentToPhoneticSeq = align.AlignmentToPhoneticSeq(
        mapAlignment = StandardizeAlignment(corpus.subLabels, bmi.subLabels),
        mapLabel = (ConstantFn('global') if globalPhone
                    else AttrGetter('phone'))
    )

    initialFrame = mgc_lf0_bap.computeFirstFrameAverage(corpus, bmi.mgcOrder,
                                                        bmi.bapOrder)

    # FIXME : only works if no cross-stream stuff happening. Make more robust somehow.
    shiftToPrevTransform = xf.ShiftOutputTransform(xf.MinusPrev())

    mgcOutputTransform = dict()
    mgcInputTransform = dict()
    for outIndex in bmi.mgcSummarizer.outIndices:
        xmin, xmax = corpus.mgcLims[outIndex]
        bins = np.linspace(xmin, xmax, numTanhTransforms + 1)
        binCentres = bins[:-1] + 0.5 * np.diff(bins)
        width = (xmax - xmin) / numTanhTransforms / 2.0
        tanhOutputTransforms = [ xf.TanhTransform1D(np.array([0.0, width, binCentre])) for binCentre in binCentres ]
        outputWarp = xf.SumTransform1D([xf.IdentityTransform()] + tanhOutputTransforms).withTag(('mgcOutputWarp', outIndex))
        mgcOutputTransform[outIndex] = xf.SimpleOutputTransform(outputWarp, checkDerivPositive1D = True).withTag(('mgcOutputTransform', outIndex))
        tanhInputTransforms = [ xf.TanhTransform1D(np.array([0.0, width, binCentre])) for binCentre in binCentres ]
        inputWarp = xf.SumTransform1D([xf.IdentityTransform()] + tanhInputTransforms).withTag(('mgcInputWarp', outIndex))
        mgcInputTransform[outIndex] = xf.VectorizeTransform(inputWarp).withTag(('mgcInputTransform', outIndex))

    dist = d.AutoregressiveSequenceDist(
        bmi.maxDepth,
        alignmentToPhoneticSeq,
        [ initialFrame for i in range(bmi.maxDepth) ],
        bmi.frameSummarizer.createDist(True, lambda streamIndex:
            {
                0:
                    d.MappedInputDist(tupleMap1,
                        d.createDiscreteDist(bmi.subLabels, lambda subLabel:
                            d.createDiscreteDist(phoneList, lambda phone:
                                bmi.mgcSummarizer.createDist(False, lambda outIndex:
                                    d.DebugDist(None,
                                        d.TransformedOutputDist(mgcOutputTransform[outIndex],
                                            d.TransformedInputDist(mgcInputTransform[outIndex],
                                                #d.MappedOutputDist(shiftToPrevTransform,
                                                    d.DebugDist(None,
                                                        d.MappedInputDist(xf.AddBias(),
                                                            # arbitrary dist to get things rolling
                                                            d.LinearGaussian(np.zeros((bmi.mgcSummarizer.vectorLength(outIndex) + 1,)), 1.0, varianceFloor = 0.0)
                                                        )
                                                    ).withTag('debug-xfed')
                                                #)
                                            )
                                        )
                                    ).withTag(('debug-orig', phone, subLabel, streamIndex, outIndex))
                                )
                            )
                        )
                    )
            ,   1:
                    d.OracleDist()
            ,   2:
                    d.OracleDist()
            }[streamIndex]
        )
    )

    def drawVarious(dist, id, simpleResiduals = False, debugResiduals = False):
        assert not (simpleResiduals and debugResiduals)
        acc = d.getDefaultParamSpec().createAccG(dist)
        corpus.accumulate(acc)
        streamIndex = 0
        for outIndex in bmi.mgcSummarizer.outIndices:
            lims = corpus.mgcLims[outIndex]
            streamId = corpus.streams[streamIndex].name+str(outIndex)
            outputTransform = nodetree.findTaggedNode(dist, lambda tag: tag == ('mgcOutputTransform', outIndex))
            inputTransform = nodetree.findTaggedNode(dist, lambda tag: tag == ('mgcInputTransform', outIndex))
            # (FIXME : replace with looking up warp (=sub-transform) directly once tree structure for transforms is done)
            outputWarp = outputTransform.transform
            inputWarp = inputTransform.transform1D

            outPdf = os.path.join(figOutDir, 'warping-'+id+'-'+streamId+'.pdf')
            draw.drawWarping([outputWarp, inputWarp], outPdf = outPdf, xlims = lims, title = outPdf)

            for phone in phoneList:
                for subLabel in bmi.subLabels:
                    accOrig = nodetree.findTaggedNode(acc, lambda tag: tag == ('debug-orig', phone, subLabel, streamIndex, outIndex))
                    distOrig = nodetree.findTaggedNode(dist, lambda tag: tag == ('debug-orig', phone, subLabel, streamIndex, outIndex))

                    debugAcc = accOrig
                    subDist = distOrig.dist
                    if bmi.mgcDepth == 1:
                        outPdf = os.path.join(figOutDir, 'scatter-'+id+'-orig-'+str(phone)+'-state'+str(subLabel)+'-'+streamId+'.pdf')
                        draw.drawFor1DInput(debugAcc, subDist, outPdf = outPdf, xlims = lims, ylims = lims, title = outPdf)

                    debugAcc = nodetree.findTaggedNode(accOrig, lambda tag: tag == 'debug-xfed')
                    subDist = nodetree.findTaggedNode(distOrig, lambda tag: tag == 'debug-xfed').dist
                    if bmi.mgcDepth == 1:
                        outPdf = os.path.join(figOutDir, 'scatter-'+id+'-xfed-'+str(phone)+'-state'+str(subLabel)+'-'+streamId+'.pdf')
                        draw.drawFor1DInput(debugAcc, subDist, outPdf = outPdf, xlims = map(inputWarp, lims), ylims = map(outputWarp, lims), title = outPdf)

                    if simpleResiduals:
                        debugAcc = nodetree.findTaggedNode(accOrig, lambda tag: tag == 'debug-xfed')
                        subDist = nodetree.findTaggedNode(distOrig, lambda tag: tag == 'debug-xfed').dist
                        residuals = np.array([ subDist.dist.residual(xf.AddBias()(input), output) for input, output in zip(debugAcc.memo.inputs, debugAcc.memo.outputs) ])
                        f = lambda x: -0.5 * math.log(2.0 * math.pi) - 0.5 * x * x
                        outPdf = os.path.join(figOutDir, 'residualLogPdf-'+id+'-'+str(phone)+'-state'+str(subLabel)+'-'+streamId+'.pdf')
                        if len(residuals) > 0:
                            draw.drawLogPdf(residuals, bins = 20, fns = [f], outPdf = outPdf, title = outPdf)

                    if debugResiduals:
                        debugAcc = nodetree.findTaggedNode(accOrig, lambda tag: tag == 'debug-residual')
                        subDist = nodetree.findTaggedNode(distOrig, lambda tag: tag == 'debug-residual').dist
                        f = lambda output: subDist.logProb([], output)
                        outPdf = os.path.join(figOutDir, 'residualLogPdf-'+id+'-'+str(phone)+'-state'+str(subLabel)+'-'+streamId+'.pdf')
                        if len(debugAcc.memo.outputs) > 0:
                            draw.drawLogPdf(debugAcc.memo.outputs, bins = 20, fns = [f], outPdf = outPdf, title = outPdf)

                    # (FIXME : replace with looking up sub-transform directly once tree structure for transforms is done)
                    residualTransforms = nodetree.findTaggedNodes(distOrig, lambda tag: tag == 'residualTransform')
                    assert len(residualTransforms) <= 1
                    for residualTransform in residualTransforms:
                        outPdf = os.path.join(figOutDir, 'residualTransform-'+id+'-'+str(phone)+'-state'+str(subLabel)+'-'+streamId+'.pdf')
                        draw.drawWarping([residualTransform.transform], outPdf = outPdf, xlims = [-2.5, 2.5], title = outPdf)

    dist = timed(trn.trainEM)(dist, corpus.accumulate, minIterations = 2, maxIterations = 2)
    timed(drawVarious)(dist, id = 'xf_init', simpleResiduals = True)
    results = evaluateVarious(dist, bmi, corpus, synthOutDir, figOutDir, exptTag = 'xf_init')

    print
    print 'ESTIMATING "GAUSSIANIZATION" TRANSFORMS'
    def afterEst(dist, it):
        #timed(drawVarious)(dist, id = 'xf-it'+str(it))
        pass
    # (FIXME : change mgcInputTransform to mgcInputWarp and mgcOutputTransform to mgcOutputWarp once tree structure for transforms is done)
    mgcWarpParamSpec = d.getByTagParamSpec(lambda tag: getElem(tag, 0, 2) == 'mgcInputTransform' or getElem(tag, 0, 2) == 'mgcOutputTransform')
    dist = timed(trn.trainCGandEM)(dist, corpus.accumulate, ps = mgcWarpParamSpec, iterations = 5, length = -25, afterEst = afterEst, verbosity = 2)
    timed(drawVarious)(dist, id = 'xf', simpleResiduals = True)
    results = evaluateVarious(dist, bmi, corpus, synthOutDir, figOutDir, exptTag = 'xf')

    if studentResiduals:
        print
        print 'USING STUDENT RESIDUALS'
        dist = convertToStudentResiduals(dist, studentTag = 'student', debugTag = 'debug-residual', subtractMeanTag = 'subtractMean')
        residualParamSpec = d.getByTagParamSpec(lambda tag: tag == 'student')
        subtractMeanParamSpec = d.getByTagParamSpec(lambda tag: tag == 'subtractMean')
    else:
        print
        print 'USING TRANSFORMED-GAUSSIAN RESIDUALS'
        dist = convertToTransformedGaussianResiduals(dist, residualTransformTag = 'residualTransform', debugTag = 'debug-residual', subtractMeanTag = 'subtractMean')
        residualParamSpec = d.getByTagParamSpec(lambda tag: tag == 'residualTransform')
        subtractMeanParamSpec = d.getByTagParamSpec(lambda tag: tag == 'subtractMean')
    timed(drawVarious)(dist, id = 'xf.res_init', debugResiduals = True)
    dist = timed(trn.trainCG)(dist, corpus.accumulate, ps = residualParamSpec, length = -50, verbosity = 2)
    dist = timed(trn.trainCG)(dist, corpus.accumulate, ps = subtractMeanParamSpec, length = -50, verbosity = 2)
    timed(drawVarious)(dist, id = 'xf.res', debugResiduals = True)
    results = evaluateVarious(dist, bmi, corpus, synthOutDir, figOutDir, exptTag = 'xf.res')

    print
    print 'ESTIMATING ALL PARAMETERS'
    dist = timed(trn.trainCG)(dist, corpus.accumulate, ps = d.getDefaultParamSpec(), length = -200, verbosity = 2)
    timed(drawVarious)(dist, id = 'xf.res.xf', debugResiduals = True)
    results = evaluateVarious(dist, bmi, corpus, synthOutDir, figOutDir, exptTag = 'xf.res.xf')

    printTime('finished xf')

@codeDeps(wnet.FlatMappedNet, wnet.SequenceNet, wnet.probLeftToRightZeroNet)
class NetFor1(object):
    def __init__(self, subLabels):
        self.subLabels = subLabels

    def __call__(self, alignment):
        labelSeq = [ label for startTime, endTime, label, subAlignment in alignment ]
        net = wnet.FlatMappedNet(
            lambda label: wnet.probLeftToRightZeroNet(
                [ (label, subLabel) for subLabel in self.subLabels ],
                [ [ ((label, subLabel), adv) for adv in [0, 1] ] for subLabel in self.subLabels ]
            ),
            wnet.SequenceNet(labelSeq, None)
        )
        return net

@codeDeps(NetFor1, d.AutoregressiveNetDist, d.AutoregressiveSequenceDist,
    d.ConstantClassifier, d.FloorSetter, d.MappedInputDist, d.SimplePruneSpec,
    d.createDiscreteDist, evaluateVarious, getBmiForCorpus, getCorpus,
    getInitDist1, globalToMonophoneMap, printTime, timed,
    trn.expectationMaximization, trn.trainEM, tupleMap1Phone
)
def doFlatStartSystem(synthOutDir, figOutDir, numSubLabels = 5):
    print
    print 'TRAINING FLAT-START SYSTEM'
    printTime('started flatStart')

    corpus = getCorpus()
    bmi = getBmiForCorpus(corpus, subLabels = list(range(numSubLabels)))

    assert corpus.subLabels is None
    assert bmi.subLabels is not None
    print 'numSubLabels =', len(bmi.subLabels)

    ccProbFloor = 3e-5
    print 'ccProbFloor =', ccProbFloor

    globalDist = getInitDist1(bmi, corpus, alignmentSubLabels = None)

    # train global dist while setting floors
    globalDist, _, _, _ = trn.expectationMaximization(
        globalDist,
        corpus.accumulate,
        afterAcc = d.FloorSetter(lgFloorMult = 1e-3),
        verbosity = 2,
    )

    print 'DEBUG: converting global dist to monophone net dist'
    assert isinstance(globalDist, d.AutoregressiveSequenceDist)
    netFor = NetFor1(bmi.subLabels)
    acDist = globalToMonophoneMap(globalDist.dist, bmi)
    durDist = d.MappedInputDist(tupleMap1Phone,
        d.createDiscreteDist(bmi.subLabels, lambda subLabel:
            d.createDiscreteDist(bmi.phoneset.phoneList, lambda phone:
                d.ConstantClassifier(
                    probs = np.array([0.5, 0.5]),
                    probFloors = np.array([ccProbFloor, ccProbFloor])
                )
            )
        )
    ).withTag(('stream', 'dur'))
    pruneSpec = d.SimplePruneSpec(betaThresh = 500.0, logOccThresh = 20.0)
    dist = d.AutoregressiveNetDist(
        bmi.maxDepth, netFor, globalDist.fillFrames,
        durDist, acDist, pruneSpec
    )

    print 'DEBUG: estimating monophone net dist'
    dist = trn.trainEM(dist, timed(corpus.accumulate), deltaThresh = 1e-4, minIterations = 4, maxIterations = 10, verbosity = 2)
    results = evaluateVarious(dist, bmi, corpus, synthOutDir, figOutDir, exptTag = 'flatStart.mono')

    printTime('finished flatStart')

@codeDeps(doDecisionTreeClusteredSystem, doDumpCorpus, doFlatStartSystem,
    doGlobalSystem, doMonophoneSystem, doTimingInfoSystem, doTransformSystem
)
def run(outDir):
    synthOutDir = os.path.join(outDir, 'synth')
    figOutDir = os.path.join(outDir, 'fig')
    os.makedirs(synthOutDir)
    os.makedirs(figOutDir)
    print 'CONFIG: outDir =', outDir

    doDumpCorpus(outDir)

    doGlobalSystem(synthOutDir, figOutDir)

    doMonophoneSystem(synthOutDir, figOutDir)

    doTimingInfoSystem(synthOutDir, figOutDir)

    doDecisionTreeClusteredSystem(synthOutDir, figOutDir)

    doTransformSystem(synthOutDir, figOutDir)

    doFlatStartSystem(synthOutDir, figOutDir)
