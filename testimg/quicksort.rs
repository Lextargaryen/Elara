// High-performance generic Quicksort in Rust
pub fn quicksort<T: Ord>(slice: &mut [T]) {
    if slice.len() <= 1 {
        return;
    }
    let pivot_index = partition(slice);
    let (left, right) = slice.split_at_mut(pivot_index);
    quicksort(left);
    quicksort(&mut right[1..]);
}

fn partition<T: Ord>(slice: &mut [T]) -> usize {
    let len = slice.len();
    let pivot_idx = len - 1;
    let mut i = 0;
    for j in 0..pivot_idx {
        if slice[j] <= slice[pivot_idx] {
            slice.swap(i, j);
            i += 1;
        }
    }
    slice.swap(i, pivot_idx);
    i
}
