__author__ = 'bofallon'

import ConfigParser as cp
import argparse
import os
import sys
import traceback as tb
import util
import pysam
import logging
import random
import bam_simulation, callers, comparators, normalizers

NO_VARS_FOUND_RESULT="No variants identified"
MATCH_RESULT="Variants matched"
NO_MATCH_RESULT="Variants did not match"
MATCH_WITH_EXTRA_RESULT= "Additional false variants present"

ZYGOSITY_MATCH="Zygosity match"
ZYGOSITY_EXTRA_ALLELE="Extra allele"
ZYGOSITY_MISSING_ALLELE="Missing allele"
ZYGOSITY_MISSING_TWO_ALLELES="Missing two alleles!"

all_result_types = (MATCH_RESULT, NO_MATCH_RESULT, NO_VARS_FOUND_RESULT, MATCH_WITH_EXTRA_RESULT, ZYGOSITY_MISSING_ALLELE, ZYGOSITY_EXTRA_ALLELE)

def result_from_tuple(tup):
    """
    Comparators return a tuple consisting of unmatched_orig, matches, and unmatched_caller variants
    This examines the tuple and returns a short descriptive string of the result
    :param tup:
    :return: Short, human readable string describing result
    """
    unmatched_orig = tup[0]
    matches = tup[1]
    unmatched_caller = tup[2]

    #ONLY return a match if everything matches perfectly
    if len(unmatched_orig)==0 and len(unmatched_caller)==0 and len(matches)>0:
        return MATCH_RESULT

    if len(unmatched_orig)==0 and len(matches)>0 and len(unmatched_caller)>0:
        return MATCH_WITH_EXTRA_RESULT

    if len(unmatched_orig)>0 and len(matches)==0:
        if len(unmatched_caller)>0:
            return NO_MATCH_RESULT
        else:
            return NO_VARS_FOUND_RESULT

    return NO_MATCH_RESULT


def should_keep_dir(var_res, variant):
    """
    Decide whether or not to flag the analysis dir for this variant for non-deletion (usually, we delete all tmp dirs)
    :param var_res: 3 layer dict of the form [caller][normalizer][comparator] containing results strings
    :param var: variant
    :return: Tuple of (boolean, suffix, comment), boolean indicates keep or not, suffix is applied to the tmpdir, comment is written to a file in the dir
    """
    #Want to flag following situations:
    #vgraph / vcfeval / happy disagree on anything
    #variant match with nonorm, but mismatch with vapleft or vt
    #variant mismatch with vapleft / raw but correctly matched with vgraph / vcfeval / etc

    keep = False
    comments = []

    for caller in var_res:
        for norm in var_res[caller]:

            vgraph_result = var_res[caller][norm]["vgraph"]
            vcfeval_result = var_res[caller][norm]["vcfeval"]
            happy_result = var_res[caller][norm]["happy"]

            if vgraph_result != vcfeval_result or vcfeval_result != happy_result:
                keep = True
                # comment = "\n".join(["caller: " + caller, "norm:" + norm, "vgraph:" + vgraph_result, "vcfeval:" + vcfeval_result, "happy:"+ happy_result])
                comments.append("\n".join(["variant: " + str(variant), "caller: " + caller, "norm:" + norm, "vgraph: " + vgraph_result, "vcfeval:" + vcfeval_result, "happy:"+ happy_result]))

            if vcfeval_result == ZYGOSITY_EXTRA_ALLELE or vcfeval_result == ZYGOSITY_MISSING_ALLELE:
                keep = True
                comments.append("\n".join(["variant: " + str(variant), "caller: " + caller, "norm:" + norm, "vgraph: " + vgraph_result, "vcfeval:" + vcfeval_result, "happy:"+ happy_result]))

        nonorm_vcfeval_result = var_res[caller]["nonorm"]["vcfeval"]
        vap_vcfeval_result = var_res[caller]["vapleft"]["vcfeval"]
        vap_raw_result = var_res[caller]["vapleft"]["raw"]

        if nonorm_vcfeval_result == MATCH_RESULT and vap_vcfeval_result != MATCH_RESULT:
            keep = True
            comments.append("\n".join(["variant: " + str(variant), "caller: " + caller, "nonorm / vcfeval:" + nonorm_vcfeval_result, "vapleft / vcfeval:" + vap_vcfeval_result]))

        if vap_raw_result != MATCH_RESULT and nonorm_vcfeval_result == MATCH_RESULT:
            keep = True
            comments.append("\n".join(["variant: " + str(variant), "caller: " + caller, "vapleft / raw:" + vap_raw_result, "nonorm / vcfeval:" + nonorm_vcfeval_result]))

    return (keep, comments)

def compare_single_var(result, bedregion, orig_vars, caller_vars, comparator, inputgt, conf):
    """
    Determine a result string for the given result tuple. Not trivial since for NO_MATCH_RESULTS we need to
     determine if a simple genotype change will produce a match
    :param result: Result tuple produced by a comparator
    :param bedregion: Genomic region containing result
    :param orig_vars: 'original' (truth) variant set
    :param caller_vars: Variants produced by caller
    :param comparator: Comparator function
    :param inputgt: True variant genotype
    :param conf: Configuration
    :return:
    """
    result_str = result_from_tuple(result)
    if result_str == NO_MATCH_RESULT  and len(inputgt.split("/"))==2:
        try:
            gt_mod_vars = util.set_genotypes(caller_vars, inputgt, bedregion, conf)
            bedfile = util.region_to_bedfile(bedregion)
            gt_mod_result = comparator(orig_vars, gt_mod_vars, bedfile, conf)
            if result_from_tuple(gt_mod_result) == MATCH_RESULT:
                if inputgt in util.ALL_HET_GTS:
                    result_str = ZYGOSITY_EXTRA_ALLELE
                else:
                    result_str = ZYGOSITY_MISSING_ALLELE
        except util.GTModException as ex:
            logging.warning('Exception while attempting to modify GTs: ' + str(ex))

    return result_str

def split_results(allresults, bed):
    """
    allresults is the result of a call to a comparator, so it's a
    tuple of (unmatched_orig (FN), matches, unmatched_caller (FP)). This function
    breaks the allresults into a list with separate
    entries for each region in the bed file.
    :param allresults: Tuple containing results from a single comparator call
    :param bed: BED file to split regions by
    :return: List of tuples containing same data as allresults, but organized by bed region
    """
    reg_results = []
    for region in util.read_regions(bed):
        fns = [v for v in allresults[0] if v.chrom==region.chr and v.start >= region.start and v.start < region.end]
        matches = [v for v in allresults[1] if v[0].chrom==region.chr and v[0].start >= region.start and v[0].start < region.end]
        fps = [v for v in allresults[2] if v.chrom==region.chr and v.start >= region.start and v.start < region.end]
        reg_results.append( (fns, matches, fps) )
        #Sanity check...
        if len(fns)+len(matches)==0:
            raise ValueError('Uh oh, did not find any matching original vars for region!')

    return reg_results

def process_batch(variant_batch, batchname, conf, gt_policy, output=sys.stdout, keep_tmpdir=False, disable_flagging=False, read_depth=250):
    """
    Process the given batch of variants by creating a fake 'genome' with the variants, simulating reads from it,
     aligning the reads to make a bam file, then using different callers, variant normalizers, and variant
     comparison methods to generate results. The results are just written to a big text file, which needs to
     be parsed by a separate utility to generate anything readable.
    :param variant_batch: pysam.Variant object to simulate
    :param conf: Configuration containing paths to all required binaries / executables / genomes, etc.
    :param homs: Boolean indicating whether variants should be simulated as hets or homs
    :return:
    """

    tmpdir = "tmp-working-" + util.randstr()
    try:
        os.mkdir(tmpdir)
    except:
        pass
    os.chdir(tmpdir)

    #The GT field to use in the true input VCF
    true_gt = None
    if gt_policy == bam_simulation.ALL_HETS:
        true_gt = "0/1"
    if gt_policy == bam_simulation.ALL_HOMS:
        true_gt = "1/1"

    try:
        orig_vcf = util.write_vcf(variant_batch, "test_input.vcf", conf, true_gt)
        ref_path = conf.get('main', 'ref_genome')
        bed = util.vars_to_bed(variant_batch)
        reads = bam_simulation.gen_alt_fq(ref_path, variant_batch, read_depth, policy=gt_policy)
        bam = bam_simulation.gen_alt_bam(ref_path, conf, reads)

        var_results = {}
        variant_callers = callers.get_callers()
        variants = {}

        for caller in variant_callers:
            logging.info("Running variant caller " + caller)
            vars = variant_callers[caller](bam, ref_path, bed, conf)
            variants[caller] = vars

        remove_tmpdir = not keep_tmpdir
        for normalizer_name, normalizer in normalizers.get_normalizers().iteritems():
            logging.info("Running normalizer " + normalizer_name)
            normed_orig_vcf = normalizer(orig_vcf, conf)

            for caller in variants:
                normed_caller_vcf = normalizer(variants[caller], conf)

                for comparator_name, comparator in comparators.get_comparators().iteritems():
                    all_results = comparator(normed_orig_vcf, normed_caller_vcf, None, conf)
                    single_results = split_results(all_results, bed)
                    logging.info("Running comparator " + comparator_name)
                    for region, result in zip(util.read_regions(bed), single_results):
                        match_vars = util.find_matching_var( pysam.VariantFile(orig_vcf), region)
                        if len(match_vars)!=1:
                            raise ValueError('Unable to find original variant from region!')

                        result = compare_single_var(result, region, normed_orig_vcf, normed_caller_vcf, comparator, "/".join([str(i) for i in match_vars[0].samples[0]['GT']]), conf)

                        match_var = " ".join(str(match_vars[0]).split()[0:5])
                        if match_var not in var_results:
                            var_results[match_var] = {}
                        if caller not in var_results[match_var]:
                            var_results[match_var][caller] = {}
                        if normalizer_name not in var_results[match_var][caller]:
                            var_results[match_var][caller][normalizer_name] = {}

                        var_results[match_var][caller][normalizer_name][comparator_name] = result

        #Iterate over all results and write to standard output. We do this here instead of within the loops above
        #because it keeps results organized by variant, which makes them easier to look at
        for var, vresults in var_results.iteritems():
            for caller, cresults in vresults.iteritems():
                for normalizer_name, compresults in cresults.iteritems():
                    for comparator_name, result in compresults.iteritems():
                        output.write("Result for " + var + ": " + caller + " / " + normalizer_name + " / " + comparator_name + ": " + result + "\n")

        if not disable_flagging:
            for origvar in var_results.keys():
                keep, comments = should_keep_dir(var_results[origvar], origvar)
                if keep:
                    remove_tmpdir = False
                    with open("flag.info.txt", "a") as fh:
                        fh.write("\n\n".join(comments) + "\n")

    except Exception as ex:
        logging.error("Error processing variant batch " + batchname + " : " + str(ex))
        tb.print_exc(file=sys.stderr)
        remove_tmpdir = False
        try:
            with open("exception.info.txt", "a") as fh:
                fh.write(str(ex) + "\n")
        except:
            #we tried...
            pass

    os.chdir("..")
    if remove_tmpdir:
        os.system("rm -rf " + tmpdir)
    else:
        dirname = os.path.split(batchname)[-1]
        count = 0
        while os.path.exists(dirname):
            count += 1
            dirname = batchname + "-" + str(count)

        os.system("mv " + tmpdir + " " + dirname)


def process_vcf(vcf, gt_policy, conf, output, single_batch=False, keep_tmpdir=False):
    """
    Perform analyses for each variant in the VCF file.
    :param input_vcf:
    :param single_batch: Assume all variants in VCF are part of one batch and process them all simultaneously
    :param keep_tmpdir: Preserve tmpdirs created (otherwise delete them, unless they are flagged)
    :param conf:
    """

    input_vars = pysam.VariantFile(vcf)
    logging.info("Processing variants in file " + vcf)
    if single_batch:
        logging.info("Processing all variants as one batch")
        process_batch(list(input_vars), vcf.replace(".vcf", "-tmpfiles"), conf, gt_policy, output=output, keep_tmpdir=keep_tmpdir)
    else:
        for batchnum, batch in enumerate(util.batch_variants(input_vars, max_batch_size=1000, min_safe_dist=2000)):
            logging.info("Processing batch #" + str(batchnum) + " containing " + str(len(batch)) + " variants")
            process_batch(batch, vcf.replace(".vcf", "-tmpfiles-") + str(batchnum), conf, gt_policy, output=output, keep_tmpdir=keep_tmpdir)



if __name__=="__main__":
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S')

    parser = argparse.ArgumentParser("Inject, simulate, call, compare")
    parser.add_argument("-c", "--conf", help="Path to configuration file", default="./comp.conf")
    parser.add_argument("-v", "--vcf", help="Input vcf file(s)", nargs="+")
    parser.add_argument("-k", "--keep", help="Dont delete temporary directories", action='store_true')
    parser.add_argument("-b", "--batch", help="Treat each input VCF file as a single batch (default False)", action='store_true')
    parser.add_argument("-s", "--seed", help="Random seed", default=None)
    parser.add_argument("-o", "--output", help="Output destination", default=sys.stdout)
    parser.add_argument("--het", help="Force all simulated variants to be hets", action='store_true')
    parser.add_argument("--hom", help="Force all simulated variants to be homozygotes", action='store_true')
    args = parser.parse_args()

    conf = cp.SafeConfigParser()
    conf.read(args.conf)

    if type(args.output) is str:
        args.output = open(args.output, "w")

    if args.seed is not None:
        random.seed(args.seed)

    if args.het and args.hom:
        raise ValueError('Specify just one of --het or --hom')

    gt_policy = bam_simulation.USE_GT
    if args.het:
        gt_policy = bam_simulation.ALL_HETS
    if args.hom:
        gt_policy = bam_simulation.ALL_HOMS

    for vcf in args.vcf:
        process_vcf(vcf, gt_policy, conf, args.output, single_batch=args.batch, keep_tmpdir=args.keep)

    try:
        args.output.close()
    except:
        pass
