
import argparse
import ConfigParser as cp
import callers
import pysam
import os
import bam_simulation
import random
import string
import comparators

def process_variant(variant_batch, results, conf, batchnum, homs):
    """
    Process the given variant, update results dict
    :param variant:
    :param results_by_caller:
    :param results_by_method:
    :param conf:
    :return:
    """

    tmpdir = "tmp-working-" + str(batchnum) + "-" + "".join([random.choice(string.ascii_uppercase + string.ascii_lowercase) for _ in range(8)])
    try:
        os.mkdir(tmpdir)
    except:
        pass
    os.chdir(tmpdir)

    ref_path = conf.get('main', 'ref_genome')

    bed = callers.vars_to_bed(variant_batch)
    bam = bam_simulation.gen_alt_bam(ref_path, variant_batch, conf, homs)

    variant_callers = callers.get_callers()
    variants = {}
    for caller in variant_callers:
        vars = variant_callers[caller](bam, ref_path, bed, conf)
        variants[caller] = vars

    for variant in variant_batch:
        orig_vcf = bam_simulation.write_vcf(variant, "test_input.vcf", conf)
        bed = callers.vars_to_bed([variant])
        vgraph_comp = comparators.get_comparators()['vgraph']
        for caller, vars in variants.iteritems():

            result = comparators.compare_genotype(orig_vcf, vars, bed)
            if result is None:
                result = vgraph_comp(orig_vcf, vars, conf, bed)
            print "Result for " + " ".join( str(variant).split()[0:5]) + ": " + caller + ": " + result
            results[caller][result] += 1

    os.chdir("..")
    os.system("rm -rf " + tmpdir)

def canadd(var, batch, max_batch_size, min_safe_dist=2000):
    if len(batch)>=max_batch_size:
        return False
    for b in batch:
        if var.chrom == b.chrom and abs(b.start - var.start)<min_safe_dist:
            return False
    return True

def batch_variants(vars, max_batch_size=10):
    batches = []
    vars = list(vars)
    while len(vars)>0:
        var = vars.pop(0)
        unfilled_batches = [b for b in batches if len(b)<max_batch_size]
        found = False
        for b in unfilled_batches:
            if canadd(var, b, max_batch_size):
                b.append(var)
                found = True
                break

        if not found:
            batch = []
            batch.append(var)
            batches.append(batch)

    return batches

def var_sort(a, b):
    if a.chrom == b.chrom:
        return a.start - b.start
    if a.chrom > b.chrom:
        return -1
    else:
        return 1

def process_vcf(input_vcf, homs, conf):
    """
    Iterate over entire vcf file, processing each variant individually and collecting results
    :param input_vcf:
    :param conf:
    :return:
    """
    #Initialize results structure
    all_results = {}
    for caller_name in callers.get_callers():
        all_results[caller_name] = {
                comparators.NO_VARS_FOUND_RESULT: 0,
                comparators.NO_MATCH_RESULT: 0,
                comparators.MATCH_RESULT: 0,
                comparators.PARTIAL_MATCH: 0,
                comparators.INCORRECT_GENOTYPE_RESULT: 0
            }

    batches = batch_variants(pysam.VariantFile(input_vcf))
    assert sum([len(b) for b in batches]) == len(list(pysam.VariantFile(input_vcf)))
    #for batch in batches:
    #    print "\n Batch of size " + str(len(batch))
    #    for v in sorted(batch, cmp=var_sort):
    #        print "  " + v.chrom + "\t" + str(v.start) + "\t" + str(v.ref) + "\t" + str(v.alts[0])
    for batch in batches:
        process_variant(sorted(batch, cmp=var_sort), all_results, conf, batches.index(batch), homs)


    for caller in all_results:
        print "Caller: " + caller
        for result, count in all_results[caller].iteritems():
            print "\t\t" + result + "\t:\t" + str(count)





if __name__=="__main__":
    parser = argparse.ArgumentParser("Test variant callers")
    parser.add_argument("-c", "--conf", help="Path to configuration file", default="./comp.conf")
    parser.add_argument("-v", "--vcf", help="Input vcf file")
    parser.add_argument("--het", help="Run all variants as hets (default false, run everything as homs)", action='store_true')
    args = parser.parse_args()

    conf = cp.SafeConfigParser()
    conf.read(args.conf)

    process_vcf(args.vcf, not args.het, conf)
