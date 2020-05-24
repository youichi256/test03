#!/usr/bin/perl

use strict;
use warnings;

srand();

open(my $fh, "<", "text01.txt") || die $!;
my @line = <$fh>;
close($fh);

my $idx = int(rand($#line + 1));

my $insstr = "";
for(my $i = 0; $i < 16; $i++) {
	$insstr .= pack("c", 0x61 + int(rand(26)));
}
my @ltime = localtime();
$insstr .= sprintf(":%02d%02d%02d\n", $ltime[2], $ltime[1], $ltime[0]);

splice(@line, $idx, 0, $insstr);

open($fh, ">", "text01.txt") || die $!;
print $fh @line;
close($fh);
